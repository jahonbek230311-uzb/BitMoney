"""Runner abstraction. DockerRunner is the production sandbox."""
import json, os, shutil, subprocess, tempfile, threading, time, uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

LANGS = {
    "cpp17": {"file": "main.cpp", "compile": ["g++", "-O2", "-std=c++17", "-pipe", "-o", "{work}/prog", "{work}/main.cpp"], "run": ["{work}/prog"]},
    "c": {"file": "main.c", "compile": ["gcc", "-O2", "-std=c17", "-pipe", "-o", "{work}/prog", "{work}/main.c"], "run": ["{work}/prog"]},
    "python3": {"file": "main.py", "compile": ["python3", "-c", "import ast,sys;ast.parse(open(sys.argv[1]).read())", "{work}/main.py"], "run": ["python3", "-B", "{work}/main.py"]},
    "java17": {"file": "Main.java", "compile": ["javac", "-encoding", "UTF-8", "-d", "{work}", "{work}/Main.java"], "run": ["java", "-cp", "{work}", "Main"]},
    "javascript": {"file": "main.js", "compile": ["node", "--check", "{work}/main.js"], "run": ["node", "{work}/main.js"]},
    "go": {"file": "main.go", "compile": ["go", "build", "-o", "{work}/prog", "{work}/main.go"], "run": ["{work}/prog"]},
    "rust": {"file": "main.rs", "compile": ["rustc", "-O", "-o", "{work}/prog", "{work}/main.rs"], "run": ["{work}/prog"]},
    "ruby": {"file": "main.rb", "compile": ["ruby", "-c", "{work}/main.rb"], "run": ["ruby", "{work}/main.rb"]},
    "php": {"file": "main.php", "compile": ["php", "-l", "{work}/main.php"], "run": ["php", "{work}/main.php"]},
}

MAX_LOG = 16 * 1024


class JudgeSystemError(RuntimeError):
    """Infrastructure failure. Must never be turned into a verdict."""


@dataclass
class CompileResult:
    ok: bool
    log: str


@dataclass
class RunResult:
    status: str  # OK TLE MLE RE OLE
    stdout: str
    stderr: str
    time_ms: int
    memory_kb: int
    exit_code: int | None = None
    signal: int | None = None


def run_limited(cmd, timeout, max_out=MAX_LOG, on_kill=None):
    """Run a command, capture combined output bounded to max_out bytes."""
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    buf = bytearray()

    def reader():
        while True:
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            if len(buf) < max_out:
                buf.extend(chunk[: max_out - len(buf)])
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    start, timed_out = time.monotonic(), False
    while p.poll() is None:
        if time.monotonic() - start > timeout:
            timed_out = True
            if on_kill:
                on_kill()
            p.kill()
            break
        time.sleep(0.005)
    p.wait()
    t.join(2)
    p.stdout.close()
    return p.returncode, bytes(buf).decode("utf-8", "replace"), timed_out


class Runner(ABC):
    max_output = 1 << 20
    compile_timeout = 30

    @abstractmethod
    def _compile_exec(self, workdir, cmd): ...
    @abstractmethod
    def _run_exec(self, workdir, iodir, tl, ml, cmd): ...

    def compile(self, language, workdir):
        spec = LANGS[language]
        rc, log, timed_out = self._compile_exec(workdir, spec["compile"])
        log = log.replace("/work/", "").replace(workdir + "/", "")
        if timed_out:
            return CompileResult(False, "Compilation timed out")
        return CompileResult(rc == 0, log)

    def run(self, language, workdir, input_text, tl, ml):
        iodir = tempfile.mkdtemp(prefix="io_")
        try:
            with open(os.path.join(iodir, "input.txt"), "w") as f:
                f.write(input_text)
            self._run_exec(workdir, iodir, tl, ml, LANGS[language]["run"])
            mp = os.path.join(iodir, "meta.json")
            if not os.path.exists(mp):
                raise JudgeSystemError("supervisor produced no result")
            with open(mp) as mf:
                meta = json.load(mf)

            def rd(name):
                with open(os.path.join(iodir, name), "rb") as f:
                    return f.read(self.max_output).decode("utf-8", "replace")
            return RunResult(meta["status"], rd("stdout.txt"), rd("stderr.txt")[-2048:],
                             meta["time_ms"], meta["memory_kb"], meta["exit_code"], meta["signal"])
        finally:
            shutil.rmtree(iodir, ignore_errors=True)


class DockerRunner(Runner):
    def __init__(self, image="cpjudge-sandbox:latest", pids=64):
        self.image, self.pids = image, pids

    def _base(self, name, mem_mb):
        return ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
                "--memory", f"{mem_mb}m", "--memory-swap", f"{mem_mb}m", "--cpus", "1",
                "--pids-limit", str(self.pids), "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--ulimit", "nofile=256"]

    def _kill(self, name):
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)

    def _compile_exec(self, workdir, cmd):
        name = "cj-c-" + uuid.uuid4().hex[:12]
        full = self._base(name, 1024) + ["--user", "65534:65534", "-v", f"{workdir}:/work:rw",
                                         "-w", "/work", self.image] + [c.replace("{work}", "/work") for c in cmd]
        try:
            rc, log, timed_out = run_limited(full, self.compile_timeout, on_kill=lambda: self._kill(name))
        except FileNotFoundError:
            raise JudgeSystemError("Docker CLI not found. Install/start Docker Desktop.")
        head = log[:300]
        if rc != 0 and (rc in (125, 126, 127) or log.startswith("docker:")
                        or "error during connect" in head or "Cannot connect to the Docker daemon" in head):
            raise JudgeSystemError("Docker unavailable: " + head.strip())
        return rc, log, timed_out

    def _run_exec(self, workdir, iodir, tl, ml, cmd):
        name = "cj-r-" + uuid.uuid4().hex[:12]
        sup = ["python3", "/opt/sandbox_exec.py", "--tl", str(tl), "--ml", str(ml),
               "--max-out", str(self.max_output), "--io", "/io", "--uid", "65534", "--"]
        full = (self._base(name, ml + 64)
                + ["--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "DAC_OVERRIDE",
                   "-v", f"{workdir}:/work:ro", "-v", f"{iodir}:/io:rw", self.image]
                + sup + [c.replace("{work}", "/work") for c in cmd])
        try:
            r = subprocess.run(full, capture_output=True, timeout=tl * 2 + 15)
        except FileNotFoundError:
            raise JudgeSystemError("Docker CLI not found. Install/start Docker Desktop.")
        except subprocess.TimeoutExpired:
            self._kill(name)
            raise JudgeSystemError("container hung past supervisor deadline")
        if r.returncode != 0 and not os.path.exists(os.path.join(iodir, "meta.json")):
            raise JudgeSystemError("docker failed: " + r.stderr.decode("utf-8", "replace")[:500])
