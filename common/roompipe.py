"""Pipeline cam trong phòng, tách khỏi I/O để kiểm thử được.

Đầu vào mỗi bước: danh sách track [(track_id, (x1,y1,x2,y2))] do bộ theo dõi (YOLO + ByteTrack) cung cấp.
`identify_fn(items)` nhận [(track_id, bbox)] và trả về {track_id: {"member_id", "score", "face_found", "high"}}.
Đầu ra: số người, danh sách người đã biết danh tính, số người lạ, danh sách bàn giao từ cam cửa vừa gán.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .identity import TrackIdentity

BBox = Tuple[float, float, float, float]


class RoomPipeline:
    def __init__(self, identify_fn: Callable[[List[Tuple[int, BBox]]], Dict[int, dict]],
                 door_zone: Optional[Tuple[float, float, float, float]] = None,
                 min_box_h: int = 70, retry_s: float = 1.5, verify_s: float = 45.0,
                 votes: int = 2, strong: float = 0.70, active_ttl: float = 3.0,
                 forget_s: float = 10.0, max_per_step: int = 3):
        self.identify_fn = identify_fn
        self.door_zone = door_zone
        self.min_box_h, self.retry_s, self.verify_s = min_box_h, retry_s, verify_s
        self.votes, self.strong = votes, strong
        self.active_ttl, self.forget_s, self.max_per_step = active_ttl, forget_s, max_per_step
        self.tracks: Dict[int, TrackIdentity] = {}

    # ------------------------------------------------------------------
    def _in_door(self, bbox: BBox, frame_wh: Tuple[int, int]) -> bool:
        if not self.door_zone:
            return False
        w, h = frame_wh
        cx, cy = (bbox[0] + bbox[2]) / 2 / w, (bbox[1] + bbox[3]) / 2 / h
        x1, y1, x2, y2 = self.door_zone
        return x1 <= cx <= x2 and y1 <= cy <= y2

    def step(self, now: float, tracks: Sequence[Tuple[int, BBox]], frame_wh: Tuple[int, int],
             pending: Iterable[str] = ()) -> dict:
        bound: List[str] = []
        new_in_door: List[TrackIdentity] = []
        for tid, bbox in tracks:
            t = self.tracks.get(tid)
            if t is None:
                t = TrackIdentity(tid, now, born_in_door=self._in_door(bbox, frame_wh))
                self.tracks[tid] = t
                if t.born_in_door:
                    new_in_door.append(t)
            t.last_seen, t.bbox = now, bbox

        # bàn giao từ cam cửa: chỉ khi CHÍNH XÁC một track mới xuất hiện ở vùng cửa (tránh gán nhầm)
        assigned = {t.member_id for t in self.tracks.values() if t.member_id}
        waiting = [m for m in pending if m not in assigned]
        if len(new_in_door) == 1 and waiting:
            if new_in_door[0].bind_handoff(waiting[0], now):
                bound.append(waiting[0])

        # chọn track cần nhận diện lại
        active = [t for t in self.tracks.values() if now - t.last_seen <= self.active_ttl]
        want = []
        for t in active:
            if t.bbox is None or (t.bbox[3] - t.bbox[1]) < self.min_box_h:
                continue
            if now - t.last_attempt < self.retry_s:
                continue
            needs = t.member_id is None or t.source == "handoff" or (now - t.last_verified) >= self.verify_s
            if needs:
                want.append(t)
        want.sort(key=lambda t: (t.member_id is not None, t.last_attempt))
        want = want[: self.max_per_step]
        requests = 0
        if want:
            results = self.identify_fn([(t.track_id, t.bbox) for t in want]) or {}
            requests = len(want)
            for t in want:
                t.last_attempt = now
                r = results.get(t.track_id)
                if not r or not r.get("face_found"):
                    continue
                t.add_face(r.get("member_id"), float(r.get("score", 0.0)), now, self.votes, self.strong)

        # dọn track đã mất lâu
        for tid in [i for i, t in self.tracks.items() if now - t.last_seen > self.forget_s]:
            del self.tracks[tid]

        # loại trùng: một người chỉ gắn với một track đang hoạt động
        active = [t for t in self.tracks.values() if now - t.last_seen <= self.active_ttl]
        by_member: Dict[str, List[TrackIdentity]] = {}
        for t in active:
            if t.member_id:
                by_member.setdefault(t.member_id, []).append(t)
        for m, ts in by_member.items():
            if len(ts) > 1:
                ts.sort(key=lambda t: (t.source == "face", t.score), reverse=True)
                for loser in ts[1:]:
                    loser.reset_identity()

        identified = [{"track_id": t.track_id, "member_id": t.member_id, "score": round(t.score, 3),
                       "source": t.source} for t in active if t.member_id]
        return {"persons": len(active), "identified": identified,
                "strangers": sum(1 for t in active if t.is_stranger), "bound": bound, "requests": requests}
