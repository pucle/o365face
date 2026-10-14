"""State machine hiện diện / vắng mặt (thuần Python, không phụ thuộc thư viện ngoài).

Quy ước trạng thái:
- PRESENT: đang ở trong phòng (được nhìn thấy trong vòng `grace_s` giây gần nhất).
- AWAY:    người CÓ ca trực, mất dấu quá `grace_s` giây  -> tính là vắng mặt tạm thời.
- OUT:     chưa check-in / đã rời đi. Người KHÔNG có ca trực khi mất dấu quá `grace_s`
           chuyển thẳng sang OUT (chỉ ghi hiện diện, không tính vắng mặt).

Thời điểm bắt đầu vắng mặt được tính lùi về lần cuối nhìn thấy (last_seen), nên "từ lúc nào"
chính xác dù hệ thống chỉ xác nhận sau `grace_s` giây. Mọi khoảng vắng đều bị cắt theo ranh giới ca.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

PRESENT, AWAY, OUT = "PRESENT", "AWAY", "OUT"


@dataclass(frozen=True)
class Shift:
    member_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Absence:
    member_id: str
    start: datetime
    end: datetime

    @property
    def minutes(self) -> float:
        return round((self.end - self.start).total_seconds() / 60.0, 1)


@dataclass
class _State:
    status: str = OUT
    last_seen: Optional[datetime] = None
    away_from: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None


class PresenceEngine:
    def __init__(
        self,
        grace_s: int = 120,
        min_absence_s: int = 60,
        on_absence: Optional[Callable[[Absence], None]] = None,
        on_event: Optional[Callable[[datetime, str, str], None]] = None,
    ):
        self.grace_s = grace_s
        self.min_absence_s = min_absence_s
        self.on_absence = on_absence
        self.on_event = on_event
        self.shifts: Dict[str, List[Shift]] = {}
        self.state: Dict[str, _State] = {}
        self.absences: List[Absence] = []

    # ---- ca trực -----------------------------------------------------
    def add_shift(self, shift: Shift) -> None:
        self.shifts.setdefault(shift.member_id, []).append(shift)

    def remove_shift(self, member_id: str, start: datetime, end: datetime) -> None:
        self.shifts[member_id] = [s for s in self.shifts.get(member_id, [])
                                  if not (s.start == start and s.end == end)]

    def forget(self, member_id: str, keep_shifts: bool = False) -> None:
        """Xoá trạng thái (và ca nếu không giữ) của một thành viên đã bị xoá."""
        self.state.pop(member_id, None)
        if not keep_shifts:
            self.shifts.pop(member_id, None)

    def on_shift(self, member_id: str, ts: datetime) -> bool:
        return any(s.start <= ts < s.end for s in self.shifts.get(member_id, []))

    # ---- sự kiện vào -------------------------------------------------
    def _st(self, member_id: str) -> _State:
        return self.state.setdefault(member_id, _State())

    def _emit(self, ts: datetime, kind: str, member_id: str) -> None:
        if self.on_event:
            self.on_event(ts, kind, member_id)

    def checkin(self, member_id: str, ts: datetime) -> str:
        """Cam cửa xác nhận danh tính. Trả về 'checkin' hoặc 'already'."""
        st = self._st(member_id)
        if st.status == PRESENT:
            st.last_seen = ts
            return "already"
        if st.status == AWAY:
            self._close_away(member_id, st.away_from, ts)
        st.status, st.last_seen, st.away_from, st.checked_in_at = PRESENT, ts, None, ts
        self._emit(ts, "checkin", member_id)
        return "checkin"

    def observe(self, member_id: str, ts: datetime) -> None:
        """Cam trong phòng nhìn thấy người này."""
        st = self._st(member_id)
        if st.status == AWAY:
            self._close_away(member_id, st.away_from, ts)
            self._emit(ts, "return", member_id)
        elif st.status == OUT:
            self._emit(ts, "seen_without_checkin", member_id)
            st.checked_in_at = st.checked_in_at or ts
        st.status, st.last_seen, st.away_from = PRESENT, ts, None

    def checkout(self, member_id: str, ts: datetime) -> None:
        st = self._st(member_id)
        if st.status == AWAY:
            self._close_away(member_id, st.away_from, ts)
        if st.status != OUT:
            self._emit(ts, "checkout", member_id)
        st.status, st.away_from = OUT, None

    # ---- đồng hồ -----------------------------------------------------
    def tick(self, ts: datetime) -> None:
        """Gọi định kỳ (ví dụ mỗi 15 giây)."""
        for member_id, st in self.state.items():
            if st.status == PRESENT and st.last_seen is not None:
                if (ts - st.last_seen).total_seconds() > self.grace_s:
                    if self.on_shift(member_id, st.last_seen):
                        st.status, st.away_from = AWAY, st.last_seen
                        self._emit(ts, "away", member_id)
                    else:
                        st.status = OUT
                        self._emit(ts, "left", member_id)
            elif st.status == AWAY and not self.on_shift(member_id, ts):
                # hết ca mà vẫn chưa quay lại: đóng khoảng vắng tại cuối ca
                self._close_away(member_id, st.away_from, ts)
                st.status, st.away_from = OUT, None
                self._emit(ts, "left", member_id)

    # ---- nội bộ ------------------------------------------------------
    def _close_away(self, member_id: str, start: Optional[datetime], end: datetime) -> None:
        if start is None:
            return
        for s in self.shifts.get(member_id, []):
            a, b = max(start, s.start), min(end, s.end)
            if (b - a).total_seconds() >= self.min_absence_s:
                ab = Absence(member_id, a, b)
                self.absences.append(ab)
                if self.on_absence:
                    self.on_absence(ab)

    # ---- truy vấn ----------------------------------------------------
    def occupants(self) -> List[str]:
        return sorted(m for m, st in self.state.items() if st.status == PRESENT)

    def away_now(self) -> List[str]:
        return sorted(m for m, st in self.state.items() if st.status == AWAY)

    def status_of(self, member_id: str) -> str:
        return self.state.get(member_id, _State()).status

    def summary(self, member_id: str, shift: Shift) -> dict:
        items = [a for a in self.absences
                 if a.member_id == member_id and a.start >= shift.start and a.end <= shift.end]
        return {
            "member_id": member_id,
            "shift": (shift.start.isoformat(), shift.end.isoformat()),
            "absences": [{"from": a.start.strftime("%H:%M"), "to": a.end.strftime("%H:%M"),
                          "minutes": a.minutes} for a in items],
            "total_minutes": round(sum(a.minutes for a in items), 1),
        }

    # ---- lưu / khôi phục (để khởi động lại giữa ngày không mất trạng thái) -----
    def snapshot(self) -> dict:
        def f(d: Optional[datetime]) -> Optional[str]:
            return d.isoformat() if d else None
        return {m: {"status": s.status, "last_seen": f(s.last_seen), "away_from": f(s.away_from),
                    "checked_in_at": f(s.checked_in_at)} for m, s in self.state.items()}

    def restore(self, data: dict, now: datetime, max_age_s: int = 6 * 3600) -> int:
        """Khôi phục trạng thái đã lưu. Bỏ qua mục quá cũ. Trả về số mục được khôi phục."""
        n = 0
        for m, d in (data or {}).items():
            try:
                ls = datetime.fromisoformat(d["last_seen"]) if d.get("last_seen") else None
                af = datetime.fromisoformat(d["away_from"]) if d.get("away_from") else None
                ci = datetime.fromisoformat(d["checked_in_at"]) if d.get("checked_in_at") else None
            except (ValueError, TypeError, KeyError):
                continue
            ref = ls or af
            if ref is None or (now - ref).total_seconds() > max_age_s or ref.date() != now.date():
                continue
            self.state[m] = _State(d.get("status", OUT), ls, af, ci)
            n += 1
        return n
