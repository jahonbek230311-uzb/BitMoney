import unittest
from judge.checker import compare


class T(unittest.TestCase):
    def test_tokens(self):
        self.assertTrue(compare("1 2\n3\n", "1   2 3"))
        self.assertFalse(compare("1 2 3", "1 2 4"))
        self.assertFalse(compare("1 2", "1 2 3"))
        self.assertFalse(compare("1", ""))

    def test_lines(self):
        self.assertTrue(compare("a b\nc\n\n", "a b  \r\nc", "lines"))
        self.assertFalse(compare("a b\nc", "a\nb\nc", "lines"))

    def test_exact(self):
        self.assertTrue(compare("a  b\n", "a  b", "exact"))
        self.assertFalse(compare("a  b", "a b", "exact"))

    def test_float(self):
        self.assertTrue(compare("3.1415926", "3.1415927", "float"))
        self.assertFalse(compare("3.14", "3.2", "float"))
        self.assertFalse(compare("1.0 x", "1.0 y", "float"))

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            compare("a", "a", "nope")


if __name__ == "__main__":
    unittest.main()
