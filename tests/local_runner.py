import os, subprocess, sys
from judge.runners import Runner, run_limited

SUP = os.path.join(os.path.dirname(__file__), "..", "judge", "sandbox_exec.py")


class LocalRunner(Runner):
    """TEST ONLY. Runs on the host WITHOUT isolation; exercises the real supervisor."""
    def _compile_exec(self, workdir, cmd):
        return run_limited([c.replace("{work}", workdir) for c in cmd], self.compile_timeout)

    def _run_exec(self, workdir, iodir, tl, ml, cmd):
        full = [sys.executable, SUP, "--tl", str(tl), "--ml", str(ml), "--max-out", str(self.max_output),
                "--io", iodir, "--as-limit", "--"] + [c.replace("{work}", workdir) for c in cmd]
        subprocess.run(full, capture_output=True, timeout=tl * 2 + 15)
