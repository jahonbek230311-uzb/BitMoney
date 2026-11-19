import unittest
from judge.engine import judge, TestInput
import os
from judge.runners import DockerRunner
from tests.local_runner import LocalRunner

R = DockerRunner() if os.environ.get('JUDGE_RUNNER') == 'docker' else LocalRunner()
TESTS = [TestInput(1, "1 2\n", "3\n"), TestInput(2, "10 -4\n", "6\n"), TestInput(3, "0 0\n", "0\n")]
ML = 128
CPP_OK = "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<\"\\n\";}"
PY_OK = "a,b=map(int,input().split())\nprint(a+b)"


def J(lang, src, tests=TESTS, tl=1.0, **kw):
    return judge(R, lang, src, tests, tl, ML, **kw)


class JudgeTests(unittest.TestCase):
    def test_ac(self):
        for lang, src in (("cpp17", CPP_OK), ("python3", PY_OK)):
            r = J(lang, src)
            self.assertEqual((r.verdict, r.passed, r.total), ("AC", 3, 3), lang)

    def test_wa_partial(self):
        r = J("python3", "a,b=map(int,input().split())\nprint(a+b if b>=0 else 0)")
        self.assertEqual(r.verdict, "WA")
        self.assertEqual([t.verdict for t in r.tests], ["AC", "WA", "AC"])
        self.assertEqual(r.passed, 2)

    def test_stop_on_fail(self):
        r = J("python3", "print(0)", stop_on_fail=True)
        self.assertEqual((r.verdict, len(r.tests)), ("WA", 1))

    def test_tle(self):
        for lang, src in (("cpp17", "int main(){volatile long x=0;for(;;)x++;}"),
                          ("python3", "while True: pass")):
            self.assertEqual(J(lang, src, tests=TESTS[:1]).verdict, "TLE", lang)

    def test_tle_sleep(self):
        self.assertEqual(J("python3", "import time\ntime.sleep(10)", tests=TESTS[:1]).verdict, "TLE")

    def test_re(self):
        self.assertEqual(J("cpp17", "int main(){int*p=0;*p=1;}", tests=TESTS[:1]).verdict, "RE")
        self.assertEqual(J("python3", "import sys\nsys.exit(3)", tests=TESTS[:1]).verdict, "RE")
        self.assertEqual(J("python3", "1/0", tests=TESTS[:1]).verdict, "RE")

    def test_ce(self):
        r = J("cpp17", "int main( { }")
        self.assertEqual(r.verdict, "CE")
        self.assertIn("error", r.compile_log)
        self.assertEqual(J("python3", "def f(:\n  pass").verdict, "CE")

    def test_mle(self):
        r = J("cpp17", "#include <vector>\nint main(){std::vector<char> v(1500000000,1);return v[5]-1;}",
              tests=TESTS[:1])
        self.assertEqual(r.verdict, "MLE")
        self.assertEqual(J("python3", "x=bytearray(1500000000)", tests=TESTS[:1]).verdict, "MLE")

    def test_ole(self):
        r = J("python3", "import sys\nwhile True: sys.stdout.write('x'*100000)", tests=TESTS[:1], tl=5.0)
        self.assertEqual(r.verdict, "RE")
        self.assertEqual(r.tests[0].message, "output limit exceeded")

    def test_source_too_large(self):
        self.assertEqual(J("python3", "#" * 70000).verdict, "CE")

    def test_metrics(self):
        self.assertGreaterEqual(J("cpp17", CPP_OK).max_memory_kb, 1)


if __name__ == "__main__":
    unittest.main()
