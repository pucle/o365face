import unittest

import numpy as np

import _path  # noqa: F401
from common.matching import Gallery


class MatchingTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.rng = rng
        self.a = rng.normal(size=512).astype(np.float32)
        self.b = rng.normal(size=512).astype(np.float32)
        self.g = Gallery()
        self.g.add("an", self.a, {"source": "door"})
        self.g.add("an", self.a + 0.3 * rng.normal(size=512).astype(np.float32), {"source": "room"})
        self.g.add("binh", self.b, {"source": "door"})

    def test_match_returns_right_member_with_margin(self):
        who, score, margin = self.g.match(self.a + 0.05)
        self.assertEqual(who, "an")
        self.assertGreater(score, 0.9)
        self.assertGreater(margin, 0.5)

    def test_unknown_face_scores_low(self):
        _, score, _ = self.g.match(np.random.default_rng(99).normal(size=512).astype(np.float32))
        self.assertLess(score, 0.3)

    def test_empty_gallery(self):
        self.assertEqual(Gallery().match(self.a), (None, -1.0, 0.0))
        self.assertEqual(Gallery().decide(self.a, 0.4, 0.05)["reason"], "empty_gallery")

    def test_count_max_sim_members(self):
        self.assertEqual(self.g.count("an"), 2)
        self.assertGreater(self.g.max_sim("an", self.a), 0.99)
        self.assertEqual(self.g.max_sim("khong-co", self.a), -1.0)
        self.assertEqual(self.g.members(), ["an", "binh"])

    def test_decide_reasons(self):
        ok = self.g.decide(self.a, 0.45, 0.08)
        self.assertEqual((ok["member_id"], ok["reason"]), ("an", "ok"))
        low = self.g.decide(self.rng.normal(size=512).astype(np.float32), 0.45, 0.08)
        self.assertEqual((low["member_id"], low["reason"]), (None, "low_score"))
        # hai người gần giống nhau -> margin thấp
        g = Gallery()
        g.add("x", self.a)
        g.add("y", self.a + 0.02 * self.rng.normal(size=512).astype(np.float32))
        amb = g.decide(self.a, 0.45, 0.08)
        self.assertEqual((amb["member_id"], amb["reason"]), (None, "low_margin"))

    def test_remove_member_by_source(self):
        self.assertEqual(self.g.remove_member("an", source="room"), 1)
        self.assertEqual(self.g.count("an"), 1)
        self.assertEqual(self.g.remove_member("an"), 1)
        self.assertEqual(self.g.members(), ["binh"])
        self.assertEqual(self.g.mat.shape[0], 1)

    def test_load_with_and_without_meta(self):
        g = Gallery()
        g.load([("a", self.a), ("b", self.b, {"source": "x"})])
        self.assertEqual(g.meta, [{}, {"source": "x"}])
        g.load([])
        self.assertEqual(g.ids, [])


if __name__ == "__main__":
    unittest.main()
