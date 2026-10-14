import unittest

import numpy as np

import _path  # noqa: F401
from common.kpspose import pose_from_kps
from server.memguard import MemGuard


def kps(yaw_off=0.0, nose_r=0.55, tilt=0.0):
    # mắt cách nhau 60, miệng cách mắt 70 theo chiều dọc; nose_r = vị trí mũi giữa mắt và miệng
    le, re_ = np.array([-30.0, 0.0]), np.array([30.0, 0.0])
    lm, rm = np.array([-20.0, 70.0]), np.array([20.0, 70.0])
    nose = np.array([yaw_off * 60.0, nose_r * 70.0])
    pts = np.stack([le, re_, nose, lm, rm])
    c, s = np.cos(np.radians(tilt)), np.sin(np.radians(tilt))
    return pts @ np.array([[c, -s], [s, c]]).T + 200


class KpsPose(unittest.TestCase):
    def test_frontal_is_zero(self):
        p, y, r = pose_from_kps(kps())
        self.assertAlmostEqual(y, 0, delta=0.5)
        self.assertAlmostEqual(p, 0, delta=0.5)
        self.assertAlmostEqual(r, 0, delta=0.5)

    def test_yaw_sign_and_monotonic(self):
        ys = [pose_from_kps(kps(yaw_off=o))[1] for o in (-0.4, -0.2, 0, 0.2, 0.4)]
        self.assertEqual(ys, sorted(ys))
        self.assertGreater(ys[-1], 30)
        self.assertLess(ys[0], -30)

    def test_pitch_direction(self):
        up = pose_from_kps(kps(nose_r=0.40))[0]       # mũi gần mắt hơn -> ngẩng
        down = pose_from_kps(kps(nose_r=0.70))[0]
        self.assertGreater(up, 15)
        self.assertLess(down, -15)

    def test_roll_does_not_fake_yaw(self):
        self.assertAlmostEqual(pose_from_kps(kps(tilt=20))[1], 0, delta=1.0)
        self.assertAlmostEqual(pose_from_kps(kps(tilt=20))[0], 0, delta=1.0)

    def test_degenerate(self):
        self.assertEqual(pose_from_kps(np.zeros((5, 2))), (0.0, 0.0, 0.0))


class Guard(unittest.TestCase):
    def test_levels(self):
        sheds, exits = [], []
        g = MemGuard(on_hard=lambda: sheds.append(1), exit_fn=exits.append)
        g.soft, g.hard, g.kill = 100, 200, 300
        self.assertEqual(g.check(50), "ok")
        self.assertEqual(g.check(150), "trim")
        self.assertEqual(g.check(250), "shed"); self.assertEqual(sheds, [1])
        self.assertEqual(g.check(350), "shed"); self.assertEqual(g.check(350), "shed")
        self.assertEqual(exits, [])
        self.assertEqual(g.check(350), "exit"); self.assertEqual(exits, [3])

    def test_strikes_reset(self):
        g = MemGuard(exit_fn=lambda c: None)
        g.soft, g.hard, g.kill = 100, 200, 300
        g.check(350); g.check(350); g.check(50)
        self.assertEqual(g.strikes, 0)


if __name__ == "__main__":
    unittest.main()
