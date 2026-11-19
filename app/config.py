import os
from pathlib import Path
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str
    database_url: str
    site_name: str
    admin_email: str | None
    admin_password: str | None
    session_hours: int
    cookie_secure: bool
    judge_image: str
    allow_registration: bool = False
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen2.5-coder:14b"

    @property
    def production(self):
        return self.env == "production"


def load_settings(environ=None) -> Settings:
    e = os.environ if environ is None else environ
    env = e.get("APP_ENV", "development")
    secret = e.get("SECRET_KEY", "")
    if env == "production":
        if len(secret) < 32:
            raise ConfigError("SECRET_KEY (>=32 chars) is required in production")
        db = e.get("DATABASE_URL", "")
        if not db:
            raise ConfigError("DATABASE_URL is required in production")
    else:
        secret = secret or "dev-only-not-for-production-" + "x" * 8
        db = e.get("DATABASE_URL", "sqlite:///./cpjudge.db")
    pw = e.get("ADMIN_PASSWORD") or None
    if pw is not None and len(pw) < 12:
        raise ConfigError("ADMIN_PASSWORD must be at least 12 characters")
    llm_url = (e.get("LLM_BASE_URL") or "http://127.0.0.1:11434/v1").strip().rstrip("/")
    llm_model = (e.get("LLM_MODEL") or "qwen2.5-coder:14b").strip()

    return Settings(env, secret, db, e.get("SITE_NAME", "Bit Money"), e.get("ADMIN_EMAIL") or None, pw,
                    int(e.get("SESSION_HOURS", "12")), env == "production",
                    e.get("JUDGE_IMAGE", "cpjudge-sandbox:latest"),
                    e.get("ALLOW_REGISTRATION", "0").lower() in ("1", "true", "yes"),
                    llm_url, llm_model)
