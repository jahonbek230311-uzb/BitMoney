"""Automatic tests: the admin writes only the statement.

A local AI model (Ollama/OpenAI-compatible API) writes (1) a correct solution, (2) an independent brute-force solution, (3) a seeded
input generator and the sample inputs. Everything then runs in the SAME Docker sandbox as student code:
  * expected outputs come from the solution (testgen.generate_tests),
  * every test small enough for the brute force is cross-checked; a test where the two disagree is marked INVALID,
  * on disagreement the model gets the failing case once and must fix its code.
The AI output is never trusted blindly and never runs outside the sandbox."""
import json, re

import httpx
from sqlalchemy import delete, select

from judge.checker import compare
from judge.engine import PreparedProgram
from . import testgen
from .models import ReferenceSolution, TestCase

MODES = ("tokens", "lines", "exact", "float")
NO_KEY = ("Automatic tests need a local AI model. Install Ollama, run `ollama pull qwen2.5-coder:14b`, "
          "and make sure Ollama is running on http://127.0.0.1:11434. Configure LLM_BASE_URL and LLM_MODEL if needed.")


class AutoError(Exception):
    pass


def _prompt(p):
    return f"""You prepare test data for a competitive programming problem. Reply with ONE JSON object and nothing else
(no markdown fences, no commentary).

PROBLEM TITLE: {p.title}
STATEMENT:
{p.statement}
INPUT FORMAT (may be empty): {p.input_format}
OUTPUT FORMAT (may be empty): {p.output_format}
CONSTRAINTS (may be empty): {p.constraints}
TIME LIMIT: {p.time_limit_ms} ms, MEMORY LIMIT: {p.memory_limit_mb} MB

JSON keys:
"error": null normally. If the problem cannot be tested automatically (several different answers are accepted for one
   input, it is interactive, or the statement is too vague to solve), put a short reason here and the rest may be empty.
"input_format", "output_format": concise, precise text describing the exact input and output (always provide them).
"checker_mode": "tokens" (compare whitespace separated tokens; the default), "lines", "exact" or "float" (real numbers).
"solution": complete Python 3 program (reads stdin, writes stdout) that is correct AND efficient enough for the
   largest allowed input. Use fast input (sys.stdin) when the input is large.
"brute": complete Python 3 program that is OBVIOUSLY correct: the simplest straightforward or exhaustive method, written
   independently from "solution" with a different algorithm. It may be slow; it is only run on small inputs.
"generator": complete Python 3 program. It reads one integer SEED from stdin and prints exactly ONE valid test input in
   the exact input format. Be deterministic: use random.Random(seed). Seed 1 = smallest valid input; seed 2 = largest
   valid input (maximum constraints, but keep the total size under 500 KB); seed 3 = tricky edge case; seeds 4..12 =
   SMALL random inputs (the brute force must be able to solve them); seeds 13 and above = random inputs of varied
   size, mostly small or medium, some large. Every output MUST satisfy all constraints and any guarantee in the
   statement (for example that an answer exists, distinct values, a valid graph).
"samples": list of 1 to 3 small input strings shown to students as examples (use the statement's example if it has one).
"""


def _call(settings, messages):
    """Call a local Ollama server via its OpenAI-compatible endpoint; no API key is used."""
    base_url = getattr(settings, "llm_base_url", "http://127.0.0.1:11434/v1").rstrip("/")
    model = getattr(settings, "llm_model", "qwen2.5-coder:14b")
    try:
        r = httpx.post(base_url + "/chat/completions", timeout=300,
                       headers={"content-type": "application/json"},
                       json={"model": model, "max_tokens": 16000, "messages": messages, "stream": False})
    except httpx.HTTPError as e:
        raise AutoError(NO_KEY + " Connection detail: " + str(e)[:150])
    if r.status_code != 200:
        raise AutoError(f"Local AI server error {r.status_code}: " + r.text[:250])
    try:
        return r.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise AutoError("The local AI server returned an unexpected response. Check the selected model and Ollama version.")


def parse_spec(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    i, j = t.find("{"), t.rfind("}")
    try:
        d = json.loads(t[i:j + 1])
        assert isinstance(d, dict)
    except Exception:
        raise AutoError("The AI answer was not valid JSON. Press the button again.")
    if d.get("error"):
        raise AutoError("This problem cannot be tested automatically: " + str(d["error"])[:300])
    for k in ("solution", "brute", "generator"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            raise AutoError(f"The AI answer has no '{k}'. Press the button again.")
    d["samples"] = [s for s in d.get("samples") or [] if isinstance(s, str) and s.strip()][:3]
    return d


def _build(db, p, runner, spec, count):
    """Replace all tests of the problem by freshly generated, cross-checked ones. Runs inside the sandbox slot."""
    db.execute(delete(TestCase).where(TestCase.problem_id == p.id))
    for old in db.scalars(select(ReferenceSolution).where(ReferenceSolution.problem_id == p.id)):
        db.delete(old)
    db.add(ReferenceSolution(problem_id=p.id, language="python3", source=spec["solution"]))
    if spec.get("checker_mode") in MODES:
        p.checker_mode = spec["checker_mode"]
    db.commit()
    notes = []
    for s in spec["samples"]:
        r = testgen.add_manual(db, p, s, "", True, runner)
        if not r["ok"]:
            notes.append("sample skipped: " + r["message"])
    g = testgen.generate_tests(db, p, "python3", spec["generator"], count, runner)
    notes += g["errors"]
    checked, bad = 0, []
    with PreparedProgram(runner, "python3", spec["brute"]) as B:
        if not B.ok:
            notes.append("brute-force solution does not compile: " + B.compile_result.log[:200])
        else:
            for t in db.scalars(select(TestCase).where(TestCase.problem_id == p.id).order_by(TestCase.ordinal)):
                rr = B.run(t.input_data, 4.0, 256)
                if rr.status != "OK":
                    continue                      # too big for the brute force: trusted on the solution alone
                checked += 1
                if not compare(rr.stdout, t.expected_output, p.checker_mode):
                    t.validated = False
                    bad.append({"ordinal": t.ordinal, "input": t.input_data[:400],
                                "solution": t.expected_output[:200], "brute": rr.stdout[:200]})
    db.commit()
    return {"checked": checked, "bad": bad, "notes": notes}


def create_tests(db, p, runner, settings, count, sandboxed):
    """Full flow. `sandboxed(fn)` runs fn while holding a docker slot (and maps Docker errors to HTTP 503)."""
    if p.published:
        raise AutoError("Unpublish the problem first: automatic tests replace all existing tests.")
    messages = [{"role": "user", "content": _prompt(p)}]
    attempts, res, spec = 0, None, None
    for attempts in (1, 2):
        raw = _call(settings, messages)
        spec = parse_spec(raw)
        res = sandboxed(lambda: _build(db, p, runner, spec, count))
        if not res["bad"] or attempts == 2:
            break
        b = res["bad"][0]
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": (
                         f"Your \"solution\" and \"brute\" disagreed on {len(res['bad'])} of {res['checked']} small tests.\n"
                         f"Example input:\n{b['input']}\n--- solution printed:\n{b['solution']}\n--- brute printed:\n{b['brute']}\n"
                         "Re-read the statement carefully, decide which program (or the generator, if the input was invalid) "
                         "is wrong, fix it, and return the complete JSON object again.")}]
    changed = False
    if spec.get("input_format") and not p.input_format.strip():
        p.input_format, changed = str(spec["input_format"])[:4000], True
    if spec.get("output_format") and not p.output_format.strip():
        p.output_format, changed = str(spec["output_format"])[:4000], True
    if changed:
        db.commit()
    total = testgen.valid_count(db, p.id)
    issues, _ = testgen.readiness(db, p)
    ok = not res["bad"] and not issues
    if ok:
        msg = (f"Done: {total} valid tests, sample(s) and a reference solution are ready. "
               f"{res['checked']} tests were cross-checked by an independent brute force. Review, then press Publish.")
    elif res["bad"]:
        msg = (f"The two AI solutions still disagree on {len(res['bad'])} test(s); those tests were marked INVALID. "
               "The statement may be ambiguous. Make it more precise and run again.")
    else:
        msg = "Not ready: " + "; ".join(issues) + "."
    return {"ok": ok, "message": msg, "attempts": attempts, "total_valid": total, "checked": res["checked"],
            "mismatches": res["bad"][:3], "notes": res["notes"][:10]}
