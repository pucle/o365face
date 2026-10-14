"""Hiệu chỉnh ngưỡng nhận diện từ chính dữ liệu đã đăng ký (không cần thêm ảnh) và từ mẫu "người lạ".

Ý tưởng:
- Điểm "thật" (genuine): với mỗi mẫu của một người, điểm cao nhất tới các mẫu KHÁC ẢNH của cùng người đó.
- Điểm "giả" (impostor): với mỗi mẫu, điểm cao nhất tới mẫu của người KHÁC. Thêm điểm của các mẫu "người lạ"
  (người chưa đăng ký đứng trước camera) tới thư viện: đây là bằng chứng sát thực tế nhất.
- Ngưỡng đề xuất phải cao hơn mọi điểm giả đã gặp một khoảng an toàn.
Đây là ước lượng; càng nhiều người và nhiều mẫu người lạ thì càng đáng tin.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np

from . import posebins


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


def _stats(x: Sequence[float]) -> Optional[dict]:
    if len(x) == 0:
        return None
    a = np.asarray(x, dtype=np.float64)
    return {"n": int(a.size), "min": round(float(a.min()), 4), "p5": round(float(np.percentile(a, 5)), 4),
            "median": round(float(np.median(a)), 4), "p95": round(float(np.percentile(a, 95)), 4),
            "max": round(float(a.max()), 4)}


def _hist(x: Sequence[float], lo: float = -0.2, hi: float = 1.0, bins: int = 24) -> dict:
    h, edges = np.histogram(np.asarray(x, dtype=np.float64), bins=bins, range=(lo, hi))
    return {"counts": h.tolist(), "lo": lo, "hi": hi, "bins": bins}


def analyze(rows: List[dict], strangers: Optional[np.ndarray] = None,
            high_pitch: float = 22.0, high_yaw: float = 40.0) -> dict:
    """rows: dict(member_id, vec, img, pitch, yaw, source). strangers: ma trận (n, 512) hoặc None."""
    warnings: List[str] = []
    members = sorted({r["member_id"] for r in rows})
    out: dict = {"members": len(members), "embeddings": len(rows), "strangers": 0 if strangers is None else int(len(strangers))}
    if len(rows) < 2:
        warnings.append("Chưa đủ mẫu. Đăng ký ít nhất 2 người, mỗi người 15 mẫu trở lên.")
        out.update(warnings=warnings, genuine=None, impostor=None, suggestion=None, by_view=[])
        return out

    V = _unit(np.stack([np.asarray(r["vec"], dtype=np.float32) for r in rows]))
    S = V @ V.T
    mem = np.array([r["member_id"] for r in rows])
    img = np.array([str(r.get("img", i)) for i, r in enumerate(rows)])

    genuine, impostor, imp_high = [], [], []
    for i, r in enumerate(rows):
        same = (mem == mem[i]) & (img != img[i])
        diff = mem != mem[i]
        if same.any():
            genuine.append(float(S[i, same].max()))
        if diff.any():
            v = float(S[i, diff].max())
            impostor.append(v)
            if posebins.is_high_angle(r.get("pitch") or 0.0, r.get("yaw") or 0.0, high_pitch, high_yaw):
                imp_high.append(v)

    stranger_scores: List[float] = []
    if strangers is not None and len(strangers):
        st = _unit(np.asarray(strangers, dtype=np.float32))
        stranger_scores = (st @ V.T).max(axis=1).tolist()

    if len(members) < 2 and not stranger_scores:
        warnings.append("Chỉ có 1 người đăng ký và chưa có mẫu người lạ: chưa thể ước lượng điểm của người lạ. "
                        "Hãy đăng ký thêm 1 người hoặc dùng nút 'Lưu làm người lạ' ở trang Thử nhận diện.")

    all_imp = impostor + stranger_scores
    imp_max = max(all_imp) if all_imp else None
    gen_p5 = float(np.percentile(genuine, 5)) if genuine else None

    suggestion = None
    if imp_max is not None:
        door = float(np.clip(max(0.35, imp_max + 0.05), 0.30, 0.85))
        room = float(np.clip(max(0.32, imp_max + 0.03), 0.28, 0.85))
        hi_pool = imp_high + stranger_scores
        room_hi = float(np.clip(max(0.30, (max(hi_pool) if hi_pool else imp_max) + 0.03), 0.26, 0.85))
        room_hi = min(room_hi, room)
        suggestion = {"door_threshold": round(door, 2), "room_threshold": round(room, 2),
                      "room_threshold_high": round(room_hi, 2)}
        if gen_p5 is not None and gen_p5 < door:
            warnings.append(f"5% mẫu thật có điểm {gen_p5:.2f}, thấp hơn ngưỡng cửa đề xuất {door:.2f}: "
                            "người đó có thể bị từ chối. Hãy đăng ký thêm mẫu ở các góc còn thiếu.")
        if imp_max > 0.5:
            warnings.append(f"Có cặp khác người đạt điểm {imp_max:.2f} (rất cao): kiểm tra mẫu bị nhầm tên, "
                            "hoặc đăng ký lại bằng ảnh rõ nét hơn.")
    if len(stranger_scores) < 5:
        warnings.append("Nên có ít nhất 5 lượt người lạ (nút 'Lưu làm người lạ') để ngưỡng đáng tin hơn.")

    # độ giảm điểm theo góc nhìn: so mỗi mẫu với các mẫu "thẳng-ngang" khác ảnh của cùng người
    by_view: List[dict] = []
    frontal_mask = np.array([posebins.bin_of(r.get("pitch") or 0.0, r.get("yaw") or 0.0) == ("level", "C") for r in rows])
    acc: Dict[str, List[float]] = {p: [] for p in posebins.PITCH_NAMES}
    for i, r in enumerate(rows):
        if r.get("pitch") is None or r.get("yaw") is None:
            continue
        ref = (mem == mem[i]) & (img != img[i]) & frontal_mask
        if ref.any():
            acc[posebins.bin_of(r["pitch"], r["yaw"])[0]].append(float(S[i, ref].max()))
    for p in posebins.PITCH_NAMES:
        s = _stats(acc[p])
        by_view.append({"pitch_bin": p, "label": posebins.PITCH_LABELS[p], "stats": s})

    out.update(genuine=_stats(genuine), impostor=_stats(impostor), stranger=_stats(stranger_scores),
               suggestion=suggestion, warnings=warnings, by_view=by_view,
               hist={"genuine": _hist(genuine) if genuine else None,
                     "impostor": _hist(all_imp) if all_imp else None})
    return out
