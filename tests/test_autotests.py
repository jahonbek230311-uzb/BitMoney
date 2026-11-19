"""Pure parts of the automatic test creation (no Docker, no network)."""
import unittest
from types import SimpleNamespace

from app import autotests


class Parse(unittest.TestCase):
    GOOD = '{"error": null, "solution": "print(1)", "brute": "print(1)", "generator": "print(1)", "samples": ["1\\n", ""]}'

    def test_plain_and_fenced_json(self):
        for text in (self.GOOD, "```json\n" + self.GOOD + "\n```", "Here you go:\n" + self.GOOD):
            self.assertEqual(autotests.parse_spec(text)["samples"], ["1\n"])

    def test_error_missing_key_and_garbage(self):
        with self.assertRaises(autotests.AutoError):
            autotests.parse_spec('{"error": "interactive problem"}')
        with self.assertRaises(autotests.AutoError):
            autotests.parse_spec('{"solution": "x", "brute": "", "generator": "y"}')
        with self.assertRaises(autotests.AutoError):
            autotests.parse_spec("not json at all")

    def test_missing_key_message(self):
        s = SimpleNamespace(llm_base_url="http://127.0.0.1:11434/v1", llm_model="m")
        with self.assertRaises(autotests.AutoError) as cm:
            autotests._call(s, [])
        self.assertIn("Install Ollama", str(cm.exception))

    def test_prompt_contains_statement(self):
        p = SimpleNamespace(title="T", statement="STATEMENT-X", input_format="", output_format="", constraints="",
                            time_limit_ms=1000, memory_limit_mb=256)
        self.assertIn("STATEMENT-X", autotests._prompt(p))


if __name__ == "__main__":
    unittest.main()
