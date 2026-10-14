import unittest
from datetime import datetime

import _path  # noqa: F401
from common.presence import AWAY, OUT, PRESENT, PresenceEngine, Shift


def t(h, m=0, s=0):
    return datetime(2026, 10, 9, h, m, s)


class PresenceTests(unittest.TestCase):
    def make(self, **kw):
        e = PresenceEngine(grace_s=120, min_absence_s=60, **kw)
        e.add_shift(Shift("an", t(9), t(12)))
        return e

    def test_absence_during_shift_is_recorded_with_backdated_start(self):
        e = self.make()
        e.checkin("an", t(9, 0))
        e.observe("an", t(10, 0))
        e.tick(t(10, 3))
        self.assertEqual(e.state["an"].status, AWAY)
        e.observe("an", t(10, 15))
        self.assertEqual(len(e.absences), 1)
        a = e.absences[0]
        self.assertEqual((a.start, a.end, a.minutes), (t(10, 0), t(10, 15), 15.0))
        self.assertEqual(e.state["an"].status, PRESENT)

    def test_short_gap_within_grace_is_not_absence(self):
        e = self.make()
        e.checkin("an", t(9))
        e.observe("an", t(10, 0))
        e.tick(t(10, 1))
        e.observe("an", t(10, 1, 30))
        self.assertEqual(e.absences, [])

    def test_non_shift_member_is_only_tracked_not_absent(self):
        e = self.make()
        e.checkin("binh", t(10))
        e.observe("binh", t(10, 5))
        e.tick(t(10, 10))
        self.assertEqual(e.state["binh"].status, OUT)
        e.observe("binh", t(10, 30))
        self.assertEqual(e.absences, [])
        self.assertEqual(e.occupants(), ["binh"])

    def test_absence_open_at_shift_end_is_closed_at_shift_end(self):
        e = self.make()
        e.checkin("an", t(9))
        e.observe("an", t(11, 40))
        e.tick(t(11, 43))
        e.tick(t(12, 5))
        self.assertEqual(len(e.absences), 1)
        self.assertEqual((e.absences[0].start, e.absences[0].end), (t(11, 40), t(12)))
        self.assertEqual(e.state["an"].status, OUT)

    def test_absence_before_shift_start_is_not_counted(self):
        e = self.make()
        e.checkin("an", t(8, 50))
        e.observe("an", t(8, 55))
        e.tick(t(9, 0, 30))
        self.assertEqual(e.state["an"].status, OUT)
        self.assertEqual(e.absences, [])

    def test_tiny_absence_below_minimum_is_ignored(self):
        e = PresenceEngine(grace_s=10, min_absence_s=60)
        e.add_shift(Shift("an", t(9), t(12)))
        e.checkin("an", t(9))
        e.observe("an", t(10, 0, 0))
        e.tick(t(10, 0, 20))
        e.observe("an", t(10, 0, 40))
        self.assertEqual(e.absences, [])

    def test_summary_totals_minutes(self):
        e = self.make()
        e.checkin("an", t(9))
        for start, back in [((10, 0), (10, 15)), ((11, 0), (11, 10))]:
            e.observe("an", t(*start))
            e.tick(t(start[0], start[1] + 3))
            e.observe("an", t(*back))
        s = e.summary("an", Shift("an", t(9), t(12)))
        self.assertEqual(s["total_minutes"], 25.0)
        self.assertEqual([x["from"] for x in s["absences"]], ["10:00", "11:00"])

    def test_checkin_twice_returns_already(self):
        e = self.make()
        self.assertEqual(e.checkin("an", t(9)), "checkin")
        self.assertEqual(e.checkin("an", t(9, 1)), "already")

    def test_events_and_callbacks_fire(self):
        events, absences = [], []
        e = PresenceEngine(grace_s=60, min_absence_s=30,
                           on_event=lambda ts, k, m: events.append((k, m)),
                           on_absence=absences.append)
        e.add_shift(Shift("an", t(9), t(12)))
        e.checkin("an", t(9, 0))
        e.observe("an", t(9, 30))
        e.tick(t(9, 32))
        e.observe("an", t(9, 40))
        self.assertEqual([k for k, _ in events], ["checkin", "away", "return"])
        self.assertEqual(len(absences), 1)

    def test_snapshot_restore_roundtrip_same_day(self):
        e = self.make()
        e.checkin("an", t(9))
        e.observe("an", t(10, 0))
        e.tick(t(10, 3))                    # AWAY từ 10:00
        snap = e.snapshot()
        e2 = self.make()
        n = e2.restore(snap, t(10, 5))
        self.assertEqual(n, 1)
        self.assertEqual(e2.state["an"].status, AWAY)
        e2.observe("an", t(10, 20))
        self.assertEqual(e2.absences[0].minutes, 20.0)

    def test_restore_ignores_stale_or_other_day(self):
        e = self.make()
        e.checkin("an", t(9))
        snap = e.snapshot()
        self.assertEqual(self.make().restore(snap, t(19)), 0)                     # quá 6 giờ
        self.assertEqual(self.make().restore(snap, datetime(2026, 10, 10, 9, 5)), 0)  # sang ngày khác
        self.assertEqual(self.make().restore({"x": {"last_seen": "bad"}}, t(9, 5)), 0)

    def test_remove_shift(self):
        e = self.make()
        e.remove_shift("an", t(9), t(12))
        self.assertFalse(e.on_shift("an", t(10)))


if __name__ == "__main__":
    unittest.main()
