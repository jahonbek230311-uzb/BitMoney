import unittest
from app.security import hash_password, verify_password, new_session_token, hash_token
from app.config import load_settings, ConfigError


class T(unittest.TestCase):
    def test_password(self):
        h = hash_password("correct horse 1")
        self.assertTrue(verify_password("correct horse 1", h))
        self.assertFalse(verify_password("wrong", h))
        self.assertNotEqual(h, hash_password("correct horse 1"))  # unique salt
        self.assertFalse(verify_password("x", "garbage"))
        with self.assertRaises(ValueError):
            hash_password("short")

    def test_token(self):
        t, h = new_session_token()
        self.assertEqual(h, hash_token(t))
        self.assertNotIn(t, h)

    def test_prod_requires_secrets(self):
        with self.assertRaises(ConfigError):
            load_settings({"APP_ENV": "production"})
        with self.assertRaises(ConfigError):
            load_settings({"APP_ENV": "production", "SECRET_KEY": "x" * 40})
        s = load_settings({"APP_ENV": "production", "SECRET_KEY": "x" * 40, "DATABASE_URL": "postgresql://u@h/d"})
        self.assertTrue(s.cookie_secure and s.admin_password is None)

    def test_weak_admin_password_rejected(self):
        with self.assertRaises(ConfigError):
            load_settings({"ADMIN_PASSWORD": "short"})

    def test_dev_defaults(self):
        self.assertTrue(load_settings({}).database_url.startswith("sqlite"))


if __name__ == "__main__":
    unittest.main()
