import math


def _norm(s):
    return s.replace("\r\n", "\n").replace("\r", "\n")


def compare(expected, actual, mode="tokens", eps=1e-6):
    e, a = _norm(expected), _norm(actual)
    if mode == "exact":
        return e.rstrip("\n") == a.rstrip("\n")
    if mode == "lines":
        el = [x.rstrip() for x in e.rstrip().split("\n")]
        al = [x.rstrip() for x in a.rstrip().split("\n")]
        return el == al
    et, at = e.split(), a.split()
    if mode == "tokens":
        return et == at
    if mode == "float":
        if len(et) != len(at):
            return False
        for x, y in zip(et, at):
            if x == y:
                continue
            try:
                fx, fy = float(x), float(y)
            except ValueError:
                return False
            if math.isnan(fx) or math.isnan(fy):
                return False
            if abs(fx - fy) > eps * max(1.0, abs(fx)):
                return False
        return True
    raise ValueError("unknown checker mode: " + mode)
