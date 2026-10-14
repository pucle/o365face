"""Gán danh tính cho từng "track" (một người được theo dõi qua nhiều khung hình) bằng bỏ phiếu.

Lý do: camera trên cao hiếm khi thấy mặt rõ. Mỗi lần thấy mặt đủ rõ ta có một "phiếu"; danh tính gắn với track và
được giữ khi mặt không còn thấy. Danh tính tạm từ cam cửa ("handoff") bị thay thế nếu nhận diện khuôn mặt cho kết
quả khác đủ số phiếu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TrackIdentity:
    track_id: int
    born_at: float
    born_in_door: bool = False
    member_id: Optional[str] = None
    source: Optional[str] = None          # 'face' hoặc 'handoff'
    score: float = 0.0
    hits: Dict[str, List[float]] = field(default_factory=dict)
    unknown_hits: int = 0
    last_attempt: float = -1e9
    last_seen: float = 0.0
    last_verified: float = 0.0
    bbox: Optional[tuple] = None

    def _mean(self, m: str) -> float:
        v = self.hits.get(m) or [0.0]
        return sum(v) / len(v)

    def add_face(self, member_id: Optional[str], score: float, ts: float,
                 votes: int = 2, strong: float = 0.70, max_hist: int = 8) -> bool:
        """Thêm một kết quả nhận diện. Trả về True nếu danh tính của track thay đổi."""
        if member_id is None:
            self.unknown_hits += 1
            return False
        h = self.hits.setdefault(member_id, [])
        h.append(float(score))
        del h[:-max_hist]
        cand = max(self.hits, key=lambda m: (len(self.hits[m]), sum(self.hits[m])))
        enough = len(self.hits[cand]) >= votes or max(self.hits[cand]) >= strong
        if not enough:
            return False
        if self.member_id is None:
            self.member_id, self.source, self.score, self.last_verified = cand, "face", self._mean(cand), ts
            return True
        if cand == self.member_id:
            self.source, self.score, self.last_verified = "face", self._mean(cand), ts
            return False
        # cand khác người đang được gán
        if self.source == "handoff":
            if len(self.hits[cand]) >= votes:
                self.member_id, self.source, self.score, self.last_verified = cand, "face", self._mean(cand), ts
                return True
            return False
        # đã gán bằng khuôn mặt: chỉ đổi khi bằng chứng mới vượt trội rõ ràng
        cur = self.member_id
        if (len(self.hits[cand]) >= votes + 1 and len(self.hits[cand]) > len(self.hits.get(cur, []))
                and self._mean(cand) >= self._mean(cur)):
            self.member_id, self.score, self.last_verified = cand, self._mean(cand), ts
            return True
        return False

    def bind_handoff(self, member_id: str, ts: float) -> bool:
        if self.member_id is None:
            self.member_id, self.source, self.score, self.last_verified = member_id, "handoff", 0.0, ts
            return True
        return False

    @property
    def is_stranger(self) -> bool:
        return self.member_id is None and self.unknown_hits >= 3

    def reset_identity(self) -> None:
        self.member_id, self.source, self.score = None, None, 0.0
        self.hits.clear()
