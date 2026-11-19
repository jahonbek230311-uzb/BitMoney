#!/usr/bin/env python3
"""In-sandbox supervisor. Runs ONE untrusted program with limits and writes
<io>/meta.json. Inside Docker it runs as root (so the child cannot touch /io),
opens all files itself, then the child drops to --uid before exec."""
import argparse, json, math, os, resource, signal, subprocess, sys, time

MEM_MARKERS = (b"MemoryError", b"bad_alloc", b"Cannot allocate memory")


def main():
    if "--" not in sys.argv:
        sys.exit("usage: sandbox_exec.py [opts] -- cmd...")
    i = sys.argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tl", type=float, required=True)        # CPU seconds
    ap.add_argument("--ml", type=int, required=True)          # MB
    ap.add_argument("--max-out", type=int, default=1 << 20)   # bytes
    ap.add_argument("--io", required=True)
    ap.add_argument("--uid", type=int, default=0)
    ap.add_argument("--as-limit", action="store_true")        # local/test mode only
    a = ap.parse_args(sys.argv[1:i])
    cmd = sys.argv[i + 1:]

    fin = os.open(os.path.join(a.io, "input.txt"), os.O_RDONLY)
    fout = os.open(os.path.join(a.io, "stdout.txt"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    ferr_path = os.path.join(a.io, "stderr.txt")
    ferr = os.open(ferr_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    cpu = int(math.ceil(a.tl)) + 1

    def preexec():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (a.max_out + 1, a.max_out + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        if a.as_limit:
            lim = a.ml * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
        if a.uid:
            os.setgroups([])
            os.setgid(a.uid)
            os.setuid(a.uid)

    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.Popen(cmd, stdin=fin, stdout=fout, stderr=ferr, preexec_fn=preexec,
                         close_fds=True, env=env)
    for fd in (fin, fout, ferr):
        os.close(fd)

    wall_limit = a.tl * 2 + 1
    start = time.monotonic()
    killed_wall = False
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        if not killed_wall and time.monotonic() - start > wall_limit:
            p.kill()
            killed_wall = True
        time.sleep(0.002)

    cpu_s = ru.ru_utime + ru.ru_stime
    mem_kb = int(ru.ru_maxrss)
    sig = os.WTERMSIG(status) if os.WIFSIGNALED(status) else None
    code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
    out_size = os.path.getsize(os.path.join(a.io, "stdout.txt"))
    with open(ferr_path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4096))
        err_tail = f.read()

    if killed_wall or cpu_s > a.tl or sig == signal.SIGXCPU:
        st = "TLE"
    elif sig == signal.SIGXFSZ or out_size > a.max_out:
        st = "OLE"
    elif mem_kb > a.ml * 1024 or any(m in err_tail for m in MEM_MARKERS):
        st = "MLE"
    elif sig is not None or code != 0:
        st = "RE"
    else:
        st = "OK"
    t_ms = int(cpu_s * 1000)
    if st == "TLE":
        t_ms = max(t_ms, int(a.tl * 1000))
    with open(os.path.join(a.io, "meta.json"), "w") as f:
        json.dump({"status": st, "exit_code": code, "signal": sig,
                   "time_ms": t_ms, "memory_kb": mem_kb}, f)


if __name__ == "__main__":
    main()
