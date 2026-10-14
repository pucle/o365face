import unittest

import _path  # noqa: F401
from common.roompipe import RoomPipeline

FRAME = (1000, 800)
DOOR = (0.0, 0.5, 0.3, 1.0)           # góc dưới-trái khung hình


def box(cx, cy, w=80, h=200):
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


class Script:
    """identify_fn giả: trả kết quả theo kịch bản cho từng track_id."""

    def __init__(self):
        self.results = {}
        self.calls = []

    def __call__(self, items):
        self.calls.append([tid for tid, _ in items])
        return {tid: self.results[tid] for tid, _ in items if tid in self.results}


class RoomPipeTests(unittest.TestCase):
    def setUp(self):
        self.s = Script()
        self.p = RoomPipeline(self.s, door_zone=DOOR, retry_s=1.0, votes=2)

    def test_identifies_after_two_votes_and_stops_asking(self):
        self.s.results[1] = {"member_id": "an", "score": 0.6, "face_found": True}
        r = self.p.step(0.0, [(1, box(500, 300))], FRAME)
        self.assertEqual((r["persons"], r["identified"]), (1, []))
        r = self.p.step(1.1, [(1, box(500, 300))], FRAME)
        self.assertEqual([x["member_id"] for x in r["identified"]], ["an"])
        before = len(self.s.calls)
        self.p.step(2.5, [(1, box(500, 300))], FRAME)
        self.assertEqual(len(self.s.calls), before)        # đã biết người, không hỏi lại ngay

    def test_retry_interval_respected(self):
        self.s.results[1] = {"member_id": None, "score": 0.1, "face_found": True}
        self.p.step(0.0, [(1, box(500, 300))], FRAME)
        self.p.step(0.4, [(1, box(500, 300))], FRAME)
        self.assertEqual(len(self.s.calls), 1)
        self.p.step(1.2, [(1, box(500, 300))], FRAME)
        self.assertEqual(len(self.s.calls), 2)

    def test_small_box_is_not_sent(self):
        self.p.step(0.0, [(1, box(500, 300, w=20, h=40))], FRAME)
        self.assertEqual(self.s.calls, [])

    def test_no_face_gives_no_vote(self):
        self.s.results[1] = {"member_id": None, "score": 0.0, "face_found": False}
        for t in (0.0, 1.1, 2.2, 3.3):
            r = self.p.step(t, [(1, box(500, 300))], FRAME)
        self.assertEqual(r["strangers"], 0)
        self.assertEqual(r["identified"], [])

    def test_stranger_after_three_unknown_faces(self):
        self.s.results[1] = {"member_id": None, "score": 0.2, "face_found": True}
        for t in (0.0, 1.1, 2.2):
            r = self.p.step(t, [(1, box(500, 300))], FRAME)
        self.assertEqual(r["strangers"], 1)

    def test_handoff_binds_single_new_track_in_door_zone(self):
        r = self.p.step(0.0, [(7, box(100, 600))], FRAME, pending=["an"])
        self.assertEqual(r["bound"], ["an"])
        self.assertEqual(r["identified"][0]["source"], "handoff")

    def test_handoff_ignored_when_two_new_tracks_in_door_zone(self):
        r = self.p.step(0.0, [(7, box(100, 600)), (8, box(150, 650))], FRAME, pending=["an"])
        self.assertEqual(r["bound"], [])
        self.assertEqual(r["identified"], [])

    def test_handoff_ignored_outside_door_zone(self):
        r = self.p.step(0.0, [(7, box(700, 300))], FRAME, pending=["an"])
        self.assertEqual(r["bound"], [])

    def test_handoff_not_bound_if_member_already_tracked(self):
        self.s.results[1] = {"member_id": "an", "score": 0.9, "face_found": True}
        self.p.step(0.0, [(1, box(500, 300))], FRAME)                         # strong hit -> an
        r = self.p.step(0.5, [(1, box(500, 300)), (7, box(100, 600))], FRAME, pending=["an"])
        self.assertEqual(r["bound"], [])

    def test_handoff_gets_corrected_by_face(self):
        self.p.step(0.0, [(7, box(100, 600))], FRAME, pending=["an"])
        self.s.results[7] = {"member_id": "binh", "score": 0.6, "face_found": True}
        self.p.step(1.1, [(7, box(120, 600))], FRAME)
        r = self.p.step(2.2, [(7, box(140, 600))], FRAME)
        self.assertEqual([(x["member_id"], x["source"]) for x in r["identified"]], [("binh", "face")])

    def test_duplicate_member_on_two_tracks_keeps_better_one(self):
        self.s.results[1] = {"member_id": "an", "score": 0.9, "face_found": True}
        self.s.results[2] = {"member_id": "an", "score": 0.75, "face_found": True}
        r = self.p.step(0.0, [(1, box(300, 300)), (2, box(600, 300))], FRAME)
        members = [x for x in r["identified"] if x["member_id"] == "an"]
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0]["track_id"], 1)

    def test_max_per_step_limit_and_persons_count(self):
        pipe = RoomPipeline(self.s, max_per_step=2)
        r = pipe.step(0.0, [(i, box(100 + 100 * i, 300)) for i in range(1, 5)], FRAME)
        self.assertEqual(r["persons"], 4)
        self.assertEqual(r["requests"], 2)

    def test_track_leaves_and_is_forgotten(self):
        self.p.step(0.0, [(1, box(500, 300))], FRAME)
        r = self.p.step(5.0, [], FRAME)
        self.assertEqual(r["persons"], 0)                  # quá active_ttl
        self.assertIn(1, self.p.tracks)
        self.p.step(20.0, [], FRAME)
        self.assertNotIn(1, self.p.tracks)                 # quá forget_s


if __name__ == "__main__":
    unittest.main()
