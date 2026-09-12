import sys
import unittest
from pathlib import Path


LIUSHEN_DIR = Path(__file__).resolve().parents[1] / "liushen"
if str(LIUSHEN_DIR) not in sys.path:
    sys.path.insert(0, str(LIUSHEN_DIR))

from flurl.extra import SM3


class SigningCompatibilityTests(unittest.TestCase):
    def test_sm3_accepts_text_and_bytes(self):
        self.assertEqual(SM3("a=1&b=2").digest(), SM3(b"a=1&b=2").digest())


if __name__ == "__main__":
    unittest.main()
