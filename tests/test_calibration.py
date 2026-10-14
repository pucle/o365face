import unittest

import numpy as np

import _path  # noqa: F401
from common import calibration as cal


def make_rows(n_members=3, per=8, noise=0.6, seed=1, dim=512):
    rng = np.random.default_rng(seed)
    rows, k = [], 0
    for m in range(n_members):
        center = rng.normal(size=dim)
        for j in range(per):
            rows.append({"member_id": f"m{m}", "vec": center + noise * rng.normal(size=dim),
                         "img": k, "pitch": -5.0 - 5 * j, "yaw": 0.0, "source": "door"})
            k += 1
    return rows


class CalibrationTests(unittest.TestCase):
    def test_separation_and_suggestion(self):
        rep = cal.analyze(make_rows())
        self.assertEqual(rep["members"], 3)
        self.assertGreater(rep["genuine"]["median"], rep["impostor"]["max"])
        s = rep["suggestion"]
        self.assertGreater(s["door_threshold"], rep["impostor"]["max"])
        self.assertLessEqual(s["room_threshold_high"], s["room_threshold"])
        self.assertIsNotNone(rep["hist"]["genuine"])

    def test_single_member_warns_and_has_no_suggestion(self):
        rep = cal.analyze(make_rows(n_members=1))
        self.assertIsNone(rep["suggestion"])
        self.assertTrue(any("1 người" in w for w in rep["warnings"]))

    def test_too_few_rows(self):
        rep = cal.analyze(make_rows(n_members=1, per=1))
        self.assertIsNone(rep["suggestion"])
        self.assertTrue(rep["warnings"])

    def test_strangers_raise_threshold(self):
        rows = make_rows(n_members=2)
        base = cal.analyze(rows)["suggestion"]["door_threshold"]
        # người lạ giống hệt một mẫu của m0 -> điểm giả rất cao
        stranger = np.asarray(rows[0]["vec"], dtype=np.float32)[None, :] + 0.2
        rep = cal.analyze(rows, strangers=stranger)
        self.assertGreater(rep["suggestion"]["door_threshold"], base)
        self.assertEqual(rep["strangers"], 1)

    def test_twin_embeddings_of_same_image_are_not_genuine_evidence(self):
        rng = np.random.default_rng(3)
        v = rng.normal(size=512)
        rows = [{"member_id": "a", "vec": v, "img": 1, "pitch": 0, "yaw": 0},
                {"member_id": "a", "vec": v, "img": 1, "pitch": 0, "yaw": 0},   # bản lật của cùng ảnh
                {"member_id": "b", "vec": rng.normal(size=512), "img": 2, "pitch": 0, "yaw": 0}]
        rep = cal.analyze(rows)
        self.assertIsNone(rep["genuine"])                  # không có cặp khác ảnh nào của cùng người

    def test_by_view_reports_pitch_bins(self):
        rep = cal.analyze(make_rows(per=10))
        labels = [b["pitch_bin"] for b in rep["by_view"]]
        self.assertEqual(labels, ["up", "level", "down1", "down2"])
        down2 = [b for b in rep["by_view"] if b["pitch_bin"] == "down2"][0]
        self.assertIsNotNone(down2["stats"])

    def test_high_similarity_between_members_is_flagged(self):
        rows = make_rows(n_members=2)
        # m1 chép gần y hệt một mẫu của m0 -> cặp khác người có điểm rất cao
        rows[-1]["vec"] = np.asarray(rows[0]["vec"]) + 0.01
        rep = cal.analyze(rows)
        self.assertTrue(any("rất cao" in w for w in rep["warnings"]))


if __name__ == "__main__":
    unittest.main()
