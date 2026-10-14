import unittest

import _path  # noqa: F401
from common import posebins as pb


class PoseBinTests(unittest.TestCase):
    def test_view_conventions(self):
        self.assertEqual(pb.to_view(-30, 15), (30.0, 15.0))     # pitch âm = cúi

    def test_bin_of(self):
        self.assertEqual(pb.bin_of(0, 0), ("level", "C"))
        self.assertEqual(pb.bin_of(-35, 0), ("down2", "C"))     # cúi 35 độ
        self.assertEqual(pb.bin_of(-20, 20), ("down1", "L1"))
        self.assertEqual(pb.bin_of(15, 0), ("up", "C"))         # ngẩng
        self.assertEqual(pb.bin_of(0, -35), ("level", "R2"))
        self.assertEqual(pb.bin_of(0, 35), ("level", "L2"))
        self.assertEqual(pb.bin_of(-12, -12), ("down1", "C"))   # biên: -12 thuộc ô thẳng (>= -12)

    def test_high_angle(self):
        self.assertFalse(pb.is_high_angle(-10, 10))
        self.assertTrue(pb.is_high_angle(-25, 0))
        self.assertTrue(pb.is_high_angle(0, -45))
        self.assertFalse(pb.is_high_angle(10, 0))               # ngẩng không phải "góc cao"

    def test_coverage_missing_score(self):
        cov = pb.coverage([(0, 0), (0, 0), (-20, 0), (None, 3)])
        self.assertEqual(cov["total"], 3)
        self.assertEqual(cov["grid"]["level"]["C"], 2)
        miss = pb.missing(cov, "door")
        self.assertIn(("level", "L1"), miss)
        self.assertNotIn(("level", "C"), miss)
        self.assertAlmostEqual(pb.score(cov, "door"), 2 / 5)    # có level-C và down1-C
        self.assertEqual(pb.score(pb.coverage([]), "room"), 0.0)

    def test_full_room_profile(self):
        pts = [(-20, 0), (-20, 20), (-20, -20), (-35, 0), (-35, 20), (-35, -20)]
        self.assertEqual(pb.score(pb.coverage(pts), "room"), 1.0)

    def test_cell_label(self):
        self.assertEqual(pb.cell_label("down2", "L1"), "Cúi nhiều · Trái")

    def test_club_grid_file_matches_python(self):
        """posebins_grid.json (dùng cho test JS) phải luôn khớp club_dir ở Python."""
        import json, os
        rows = json.load(open(os.path.join(os.path.dirname(__file__), "posebins_grid.json")))
        for pitch, yaw, p, y, club in rows:
            self.assertEqual(pb.bin_of(pitch, yaw), (p, y))
            self.assertEqual(pb.club_dir(pitch, yaw), club, (pitch, yaw))

    def test_club_windows_do_not_overlap(self):
        for pitch in range(-70, 71):
            for yaw in range(-90, 91):
                hits = [d for d in pb.CLUB_DIRS if pb.CLUB_WINDOWS[d][0] <= pitch <= pb.CLUB_WINDOWS[d][1]
                        and pb.CLUB_WINDOWS[d][2] <= yaw <= pb.CLUB_WINDOWS[d][3]]
                self.assertLessEqual(len(hits), 1, (pitch, yaw, hits))

    def test_club_targets_inside_own_window(self):
        for d, (p, y) in pb.CLUB_TARGETS.items():
            self.assertEqual(pb.club_dir(p, y), d)


if __name__ == "__main__":
    unittest.main()
