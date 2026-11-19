import os, shutil, tempfile
from dataclasses import dataclass, field
from .checker import compare
from .runners import LANGS, CompileResult, Runner

MAX_SOURCE = 64 * 1024
VERDICT_OF = {"TLE": "TLE", "MLE": "MLE", "RE": "RE", "OLE": "RE"}


@dataclass
class TestInput:
    __test__ = False
    id: int
    input: str
    expected: str


@dataclass
class TestVerdict:
    __test__ = False
    test_id: int
    verdict: str
    time_ms: int = 0
    memory_kb: int = 0
    message: str = ""
    output: str = ""
    stderr: str = ""


@dataclass
class JudgeResult:
    verdict: str
    tests: list = field(default_factory=list)
    compile_log: str = ""
    max_time_ms: int = 0
    max_memory_kb: int = 0
    passed: int = 0
    total: int = 0


class PreparedProgram:
    """Compile once, run many times, always clean up. Raises JudgeSystemError on infra failure."""

    def __init__(self, runner: Runner, language: str, source: str):
        if language not in LANGS:
            raise ValueError("unsupported language")
        self.runner, self.language, self.source = runner, language, source
        self.work = None
        self.compile_result = None

    def __enter__(self):
        if len(self.source.encode()) > MAX_SOURCE:
            self.compile_result = CompileResult(False, "Source too large (limit 64 KB)")
            return self
        self.work = tempfile.mkdtemp(prefix="work_")
        try:
            os.chmod(self.work, 0o777)
            src = os.path.join(self.work, LANGS[self.language]["file"])
            with open(src, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.source)
            os.chmod(src, 0o644)
            self.compile_result = self.runner.compile(self.language, self.work)
            if self.compile_result.ok:
                os.chmod(self.work, 0o755)
                prog = os.path.join(self.work, "prog")
                if os.path.exists(prog):
                    os.chmod(prog, 0o755)
        except BaseException:
            shutil.rmtree(self.work, ignore_errors=True)
            raise
        return self

    @property
    def ok(self):
        return bool(self.compile_result and self.compile_result.ok)

    def run(self, input_text, tl, ml):
        return self.runner.run(self.language, self.work, input_text, tl, ml)

    def __exit__(self, *exc):
        if self.work:
            shutil.rmtree(self.work, ignore_errors=True)
        return False


def judge(runner: Runner, language, source, tests, tl, ml, checker="tokens",
          stop_on_fail=False, capture=False):
    with PreparedProgram(runner, language, source) as prog:
        if not prog.ok:
            return JudgeResult("CE", compile_log=prog.compile_result.log, total=len(tests))
        res = JudgeResult("AC", compile_log=prog.compile_result.log, total=len(tests))
        first_bad = None
        for t in tests:
            rr = prog.run(t.input, tl, ml)
            if rr.status == "OK":
                v = "AC" if compare(t.expected, rr.stdout, checker) else "WA"
            else:
                v = VERDICT_OF[rr.status]
            tv = TestVerdict(t.id, v, rr.time_ms, rr.memory_kb,
                             "output limit exceeded" if rr.status == "OLE" else "")
            if capture:
                tv.output, tv.stderr = rr.stdout[:2000], rr.stderr[:1000]
            res.tests.append(tv)
            res.max_time_ms = max(res.max_time_ms, rr.time_ms)
            res.max_memory_kb = max(res.max_memory_kb, rr.memory_kb)
            if v == "AC":
                res.passed += 1
            elif first_bad is None:
                first_bad = v
                if stop_on_fail:
                    break
        res.verdict = first_bad or "AC"
        return res
