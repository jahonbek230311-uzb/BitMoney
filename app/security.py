import base64, hashlib, hmac, os, secrets

_N, _R, _P = 2**15, 8, 1
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                              p=int(p), maxmem=_MAXMEM, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def new_session_token() -> tuple[str, str]:
    """Returns (token_for_cookie, sha256_hex_to_store). DB never holds the raw token."""
    t = secrets.token_urlsafe(32)
    return t, hash_token(t)


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()
