import unittest

import _path  # noqa: F401
from common.identity import TrackIdentity


def tr():
    return TrackIdentity(1, born_at=0.0)


class IdentityTests(unittest.TestCase):
    def test_needs_votes(self):
        t = tr()
        self.assertFalse(t.add_face("an", 0.5, 1, votes=2))
        self.assertIsNone(t.member_id)
        self.assertTrue(t.add_face("an", 0.5, 2, votes=2))
        self.assertEqual((t.member_id, t.source), ("an", "face"))

    def test_single_strong_hit_is_enough(self):
        t = tr()
        self.assertTrue(t.add_face("an", 0.8, 1, votes=3, strong=0.7))
        self.assertEqual(t.member_id, "an")

    def test_unknown_faces_make_stranger_only_without_identity(self):
        t = tr()
        for i in range(3):
            t.add_face(None, 0.0, i)
        self.assertTrue(t.is_stranger)
        t2 = tr()
        t2.add_face("an", 0.8, 0)
        for i in range(5):
            t2.add_face(None, 0.0, i)
        self.assertFalse(t2.is_stranger)

    def test_handoff_is_overridden_by_face_votes(self):
        t = tr()
        self.assertTrue(t.bind_handoff("an", 1))
        self.assertEqual(t.source, "handoff")
        t.add_face("binh", 0.5, 2, votes=2)
        self.assertEqual(t.member_id, "an")                # mới 1 phiếu
        self.assertTrue(t.add_face("binh", 0.52, 3, votes=2))
        self.assertEqual((t.member_id, t.source), ("binh", "face"))

    def test_handoff_confirmed_by_face_becomes_face(self):
        t = tr()
        t.bind_handoff("an", 1)
        t.add_face("an", 0.5, 2, votes=2)
        t.add_face("an", 0.55, 3, votes=2)
        self.assertEqual((t.member_id, t.source), ("an", "face"))

    def test_face_identity_is_sticky(self):
        t = tr()
        t.add_face("an", 0.6, 1)
        t.add_face("an", 0.6, 2)
        self.assertEqual(t.member_id, "an")
        # một vài phiếu lẻ cho người khác không đủ để đổi
        t.add_face("binh", 0.5, 3)
        t.add_face("binh", 0.5, 4)
        self.assertEqual(t.member_id, "an")

    def test_face_identity_switches_with_overwhelming_evidence(self):
        t = tr()
        t.add_face("an", 0.45, 1)
        t.add_face("an", 0.45, 2)
        for i in range(3, 8):
            t.add_face("binh", 0.7, i)
        self.assertEqual(t.member_id, "binh")

    def test_handoff_does_not_overwrite_existing_identity(self):
        t = tr()
        t.add_face("an", 0.8, 1)
        self.assertFalse(t.bind_handoff("binh", 2))
        self.assertEqual(t.member_id, "an")

    def test_reset(self):
        t = tr()
        t.add_face("an", 0.8, 1)
        t.reset_identity()
        self.assertIsNone(t.member_id)
        self.assertEqual(t.hits, {})


if __name__ == "__main__":
    unittest.main()
