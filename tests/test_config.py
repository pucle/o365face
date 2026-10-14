import os
import unittest

import _path  # noqa: F401
from common import config


class ConfigTests(unittest.TestCase):
    def test_defaults_have_all_keys(self):
        d = config.defaults()
        self.assertEqual(set(d), set(config.SPEC))
        self.assertIsInstance(d["door_votes"], int)

    def test_coerce_valid_and_invalid(self):
        self.assertEqual(config.coerce("door_threshold", "0.5"), 0.5)
        self.assertEqual(config.coerce("grace_s", 90.0), 90)
        with self.assertRaises(ValueError):
            config.coerce("door_threshold", 5)
        with self.assertRaises(ValueError):
            config.coerce("door_threshold", "abc")
        with self.assertRaises(ValueError):
            config.coerce("khong_co", 1)

    def test_env_override(self):
        os.environ["CHECKIN_THRESHOLD"] = "0.6"
        try:
            self.assertEqual(config.defaults()["door_threshold"], 0.6)
            os.environ["CHECKIN_THRESHOLD"] = "xyz"
            self.assertEqual(config.defaults()["door_threshold"], 0.45)
        finally:
            del os.environ["CHECKIN_THRESHOLD"]

    def test_describe(self):
        self.assertIn("help", config.describe()["grace_s"])


if __name__ == "__main__":
    unittest.main()
