"""Test-case validation and generation. Expected outputs ALWAYS come from a sandboxed reference
solution (or are manually supplied by the admin and cross-checked against the reference if present)."""
import hashlib
from sqlalchemy import func, select
from judge.checker import compare
from judge.engine import PreparedProgram
from .models import ReferenceSolution, TestCase

MAX_IO = 2 * 1024 * 1024
MIN_VALID_TESTS = 20
GEN_KINDS = ("min", "max", "edge", "generated")


def norm_input(s):
    return s.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def input_hash(s):
    return hashlib.sha256(norm_input(s).encode()).hexdigest()


def check_input(s):
    if not s.strip():
        return "empty input"
    if "\x00" in s:
        return "input contains NUL byte"
    if len(s.encode()) > MAX_IO:
        return "input larger than 2 MB"
    return None


def get_reference(db, problem):
    return db.scalar(select(ReferenceSolution).where(ReferenceSolution.problem_id == problem.id)
                     .order_by(ReferenceSolution.id.desc()))


def ref_limits(problem):
    return max(problem.time_limit_ms * 3, 3000) / 1000.0, max(problem.memory_limit_mb, 256)


def valid_count(db, problem_id):
    return db.scalar(select(func.count()).select_from(TestCase)
                     .where(TestCase.problem_id == problem_id, TestCase.validated.is_(True))) or 0


def readiness(db, problem):
    """Automatic check run before a problem is published or added to a contest.
    Returns (problems, warnings): 'problems' block the action, 'warnings' do not."""
    from sqlalchemy import select as _sel
    issues, warns = [], []
    n = valid_count(db, problem.id)
    if n < MIN_VALID_TESTS:
        issues.append(f"only {n} valid tests, need {MIN_VALID_TESTS}")
    if not get_reference(db, problem):
        issues.append("no reference solution saved")
    if not db.scalar(_sel(TestCase.id).where(TestCase.problem_id == problem.id, TestCase.is_sample.is_(True),
                                              TestCase.validated.is_(True)).limit(1)):
        issues.append("no valid sample test")
    bad = db.scalar(select(func.count()).select_from(TestCase)
                    .where(TestCase.problem_id == problem.id, TestCase.validated.is_(False))) or 0
    if bad:
        warns.append(f"{bad} invalid test(s) are ignored")
    return issues, warns


def _next_ordinal(db, pid):
    return (db.scalar(select(func.max(TestCase.ordinal)).where(TestCase.problem_id == pid)) or 0) + 1


def add_manual(db, problem, input_text, expected, is_sample, runner):
    err = check_input(input_text)
    if err:
        return {"ok": False, "message": err}
    inp = norm_input(input_text)
    h = input_hash(inp)
    if db.scalar(select(TestCase.id).where(TestCase.problem_id == problem.id, TestCase.input_hash == h)):
        return {"ok": False, "message": "duplicate input (already exists)"}
    ref = get_reference(db, problem)
    source = "admin"
    if ref:
        tl, ml = ref_limits(problem)
        with PreparedProgram(runner, ref.language, ref.source) as R:
            if not R.ok:
                return {"ok": False, "message": "reference solution does not compile: " + R.compile_result.log[:300]}
            rr = R.run(inp, tl, ml)
        if rr.status != "OK":
            return {"ok": False, "message": f"reference solution failed on this input ({rr.status})"}
        if not expected.strip():
            expected, source = rr.stdout, "reference"
        elif compare(rr.stdout, expected, problem.checker_mode):
            source = "approved"
        else:
            return {"ok": False, "message": "supplied expected output differs from reference output "
                                            "(reference printed: " + rr.stdout[:80].strip() + ")"}
    elif not expected.strip():
        return {"ok": False, "message": "no reference solution saved: expected output is required"}
    if len(expected.encode()) > MAX_IO:
        return {"ok": False, "message": "expected output larger than 2 MB"}
    db.add(TestCase(problem_id=problem.id, ordinal=_next_ordinal(db, problem.id), input_data=inp,
                    expected_output=expected, is_sample=is_sample, kind="sample" if is_sample else "manual",
                    source=source, input_hash=h, validated=True))
    db.commit()
    return {"ok": True, "message": f"test added (source: {source})"}


def generate_tests(db, problem, gen_language, gen_source, count, runner):
    rep = {"requested": count, "added": 0, "duplicates": 0, "errors": [], "total_valid": None}
    ref = get_reference(db, problem)
    if not ref:
        rep["errors"].append("Save a reference solution first.")
        return rep
    hashes = set(db.scalars(select(TestCase.input_hash).where(TestCase.problem_id == problem.id)))
    ordinal = _next_ordinal(db, problem.id)
    seed = db.scalar(select(func.count()).select_from(TestCase)
                     .where(TestCase.problem_id == problem.id, TestCase.kind.in_(GEN_KINDS))) or 0
    tl, ml = ref_limits(problem)
    with PreparedProgram(runner, gen_language, gen_source) as G, PreparedProgram(runner, ref.language, ref.source) as R:
        if not G.ok:
            rep["errors"].append("generator does not compile: " + G.compile_result.log[:300])
        elif not R.ok:
            rep["errors"].append("reference does not compile: " + R.compile_result.log[:300])
        else:
            attempts, max_attempts = 0, count * 3 + 10
            while rep["added"] < count and attempts < max_attempts:
                seed += 1
                attempts += 1
                g = G.run(f"{seed}\n", 10.0, 256)
                if g.status != "OK":
                    rep["errors"].append(f"seed {seed}: generator {g.status}")
                    continue
                err = check_input(g.stdout)
                if err:
                    rep["errors"].append(f"seed {seed}: {err}")
                    continue
                inp = norm_input(g.stdout)
                h = input_hash(inp)
                if h in hashes:
                    rep["duplicates"] += 1
                    continue
                r = R.run(inp, tl, ml)
                if r.status != "OK":
                    rep["errors"].append(f"seed {seed}: reference {r.status}")
                    continue
                if not r.stdout.strip() or len(r.stdout.encode()) > MAX_IO:
                    rep["errors"].append(f"seed {seed}: reference output empty or too large")
                    continue
                db.add(TestCase(problem_id=problem.id, ordinal=ordinal, input_data=inp, expected_output=r.stdout,
                                kind={1: "min", 2: "max", 3: "edge"}.get(seed, "generated"), source="reference",
                                input_hash=h, validated=True))
                hashes.add(h)
                ordinal += 1
                rep["added"] += 1
    db.commit()
    if rep["added"] < count:
        rep["errors"].append(f"only {rep['added']} of {count} tests could be produced")
    rep["errors"] = rep["errors"][:20]
    rep["total_valid"] = valid_count(db, problem.id)
    return rep


def revalidate(db, problem, runner):
    """Re-run the reference on every stored test; flag any whose expected output differs."""
    rep = {"checked": 0, "invalid": [], "errors": []}
    ref = get_reference(db, problem)
    if not ref:
        rep["errors"].append("Save a reference solution first.")
        return rep
    tl, ml = ref_limits(problem)
    with PreparedProgram(runner, ref.language, ref.source) as R:
        if not R.ok:
            rep["errors"].append("reference does not compile: " + R.compile_result.log[:300])
            return rep
        for t in db.scalars(select(TestCase).where(TestCase.problem_id == problem.id).order_by(TestCase.ordinal)):
            rr = R.run(t.input_data, tl, ml)
            ok = rr.status == "OK" and compare(rr.stdout, t.expected_output, problem.checker_mode)
            t.validated = ok
            rep["checked"] += 1
            if not ok:
                rep["invalid"].append({"ordinal": t.ordinal, "reason": rr.status if rr.status != "OK" else "output mismatch"})
    db.commit()
    rep["total_valid"] = valid_count(db, problem.id)
    return rep
