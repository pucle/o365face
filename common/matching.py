"""So khớp embedding khuôn mặt (cosine) với thư viện thành viên đã đăng ký."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class Gallery:
    """Mỗi thành viên có NHIỀU embedding; điểm của thành viên = cosine cao nhất trong các mẫu của họ."""

    def __init__(self) -> None:
        self.ids: List[str] = []
        self.meta: List[dict] = []
        self.mat: np.ndarray = np.zeros((0, 512), dtype=np.float32)

    def load(self, rows: List[Tuple]) -> None:
        """rows: (member_id, vec) hoặc (member_id, vec, meta_dict)."""
        self.ids = [r[0] for r in rows]
        self.meta = [(r[2] if len(r) > 2 and r[2] else {}) for r in rows]
        self.mat = np.stack([_norm(r[1]) for r in rows]) if rows else np.zeros((0, 512), np.float32)

    def add(self, member_id: str, emb: np.ndarray, meta: Optional[dict] = None) -> None:
        e = _norm(emb)[None, :]
        self.mat = e if self.mat.size == 0 else np.vstack([self.mat, e])
        self.ids.append(member_id)
        self.meta.append(meta or {})

    def remove_member(self, member_id: str, source: Optional[str] = None) -> int:
        keep = [i for i, (m, md) in enumerate(zip(self.ids, self.meta))
                if not (m == member_id and (source is None or md.get("source") == source))]
        removed = len(self.ids) - len(keep)
        self.ids = [self.ids[i] for i in keep]
        self.meta = [self.meta[i] for i in keep]
        self.mat = self.mat[keep] if keep else np.zeros((0, 512), np.float32)
        return removed

    def remove_imgs(self, member_id: str, imgs) -> int:
        imgs = set(imgs)
        keep = [i for i, (m, md) in enumerate(zip(self.ids, self.meta)) if not (m == member_id and md.get("img") in imgs)]
        removed = len(self.ids) - len(keep)
        self.ids = [self.ids[i] for i in keep]
        self.meta = [self.meta[i] for i in keep]
        self.mat = self.mat[keep] if keep else np.zeros((0, 512), np.float32)
        return removed

    def add_many(self, rows) -> None:
        """rows: (member_id, emb, meta). Thêm nhiều mẫu với một lần ghép ma trận."""
        rows = list(rows)
        if not rows:
            return
        m = np.stack([_norm(r[1]) for r in rows])
        self.mat = m if self.mat.size == 0 else np.vstack([self.mat, m])
        self.ids += [r[0] for r in rows]
        self.meta += [r[2] or {} for r in rows]

    def count(self, member_id: str) -> int:
        return sum(1 for i in self.ids if i == member_id)

    def members(self) -> List[str]:
        return sorted(set(self.ids))

    def max_sim(self, member_id: str, emb: np.ndarray) -> float:
        idx = [k for k, i in enumerate(self.ids) if i == member_id]
        if not idx:
            return -1.0
        return float((self.mat[idx] @ _norm(emb)).max())

    def scores(self, emb: np.ndarray) -> Dict[str, float]:
        """Điểm tốt nhất của từng thành viên."""
        if self.mat.size == 0:
            return {}
        sims = self.mat @ _norm(emb)
        best: Dict[str, float] = {}
        for i, s in zip(self.ids, sims):
            if s > best.get(i, -2.0):
                best[i] = float(s)
        return best

    def match(self, emb: np.ndarray) -> Tuple[Optional[str], float, float]:
        """Trả về (member_id | None, điểm tốt nhất, khoảng cách so với người thứ hai)."""
        best = self.scores(emb)
        if not best:
            return None, -1.0, 0.0
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        top_id, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        return top_id, top, top - second

    def decide(self, emb: np.ndarray, threshold: float, margin: float) -> dict:
        """Quyết định nhận/không nhận kèm lý do (dùng cho giao diện thử nhận diện)."""
        who, score, gap = self.match(emb)
        if who is None:
            return {"member_id": None, "best_id": None, "score": -1.0, "margin": 0.0, "reason": "empty_gallery"}
        if score < threshold:
            reason = "low_score"
        elif gap < margin:
            reason = "low_margin"
        else:
            reason = "ok"
        return {"member_id": who if reason == "ok" else None, "best_id": who,
                "score": round(score, 4), "margin": round(gap, 4), "reason": reason}
