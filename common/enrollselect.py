"""Chọn mẫu khuôn mặt tốt nhất từ chuỗi khung hình chụp liên tục (hàm thuần, chỉ cần numpy).

Một "ứng viên" là dict: fid, dir (hướng CLB hoặc None), pitch, yaw, det, width, blur, light (độ sáng 0..255),
clipped (mặt bị cắt khỏi khung), nfaces (số mặt lớn trong khung), emb (vector 512 đã chuẩn hoá L2).
Mọi trọng số/ngưỡng lấy từ `cfg` (xem common/config.py) chứ không hard-code ở đây.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import posebins

DEFAULT_CFG = {
    "w_det": 0.15, "w_size": 0.15, "w_blur": 0.25, "w_light": 0.10, "w_pose": 0.35,
    "min_det": 0.55, "min_w": 70, "min_blur": 12.0, "outlier_cos": 0.30, "dup_cos": 0.99,
    "target": 24, "min_per_dir": 2, "min_real": 20, "aug_min_cos": 0.60, "aug_max_ratio": 0.5, "aug_cap_total": 60,
}


def _c(cfg: Optional[dict]) -> dict:
    out = dict(DEFAULT_CFG)
    out.update(cfg or {})
    return out


def _clamp(v: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, v))


def _unit(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    n[n == 0] = 1
    return m / n


# ---------------------------------------------------------------- chấm điểm
def eligible(c: dict, cfg: Optional[dict] = None, need_emb: bool = True) -> Optional[str]:
    """None nếu khung dùng được; ngược lại trả mã lý do loại."""
    k = _c(cfg)
    if c.get("nfaces", 1) > 1:
        return "multiple_faces"
    if c.get("clipped"):
        return "clipped"
    if c.get("det", 0.0) < k["min_det"]:
        return "low_det"
    if c.get("width", 0) < k["min_w"]:
        return "small"
    if c.get("blur", 1e9) < k["min_blur"]:
        return "blurry"
    if need_emb and c.get("emb") is None:
        return "no_embedding"
    return None


def pose_score(direction: Optional[str], pitch: Optional[float], yaw: Optional[float]) -> float:
    """1 khi đúng tâm hướng, giảm dần theo khoảng cách góc (35° → 0)."""
    if direction is None or pitch is None or yaw is None:
        return 0.0
    tp, ty = posebins.CLUB_TARGETS[direction]
    return _clamp(1.0 - math.hypot(pitch - tp, yaw - ty) / 35.0)


def quality(c: dict, cfg: Optional[dict] = None) -> float:
    """Điểm 0..1 gộp từ độ tin cậy phát hiện, kích thước, độ nét, ánh sáng và độ gần góc đích."""
    k = _c(cfg)
    det = _clamp((c.get("det", 0.0) - 0.5) / 0.4)
    size = _clamp(c.get("width", 0) / 160.0)
    blur = _clamp(c.get("blur", 0.0) / 200.0)
    light = _clamp(1.0 - max(0.0, abs(c.get("light", 128.0) - 128.0) - 40.0) / 88.0)
    pose = pose_score(c.get("dir"), c.get("pitch"), c.get("yaw"))
    wsum = k["w_det"] + k["w_size"] + k["w_blur"] + k["w_light"] + k["w_pose"]
    return (k["w_det"] * det + k["w_size"] * size + k["w_blur"] * blur + k["w_light"] * light + k["w_pose"] * pose) / wsum


# ---------------------------------------------------------------- loại ngoại lai / trùng
def drop_outliers(cands: Sequence[dict], cfg: Optional[dict] = None, extra_ref: Optional[np.ndarray] = None) -> Tuple[List[dict], List[dict]]:
    """Loại khung có embedding không nhất quán với phần còn lại của phiên (người khác đi ngang, nhận nhầm...).
    extra_ref: embedding đã có của chính người này (đăng ký bổ sung) để làm mốc. Trả về (giữ, loại)."""
    k = _c(cfg)
    cands = list(cands)
    if not cands:
        return [], []
    if len(cands) < 5 and extra_ref is None:
        return cands, []
    E = _unit(np.stack([c["emb"] for c in cands]))
    ref = E if extra_ref is None or len(extra_ref) == 0 else np.vstack([E, _unit(extra_ref)])
    cen = _unit(ref.mean(axis=0, keepdims=True))[0]
    keep, drop = [], []
    for c, e in zip(cands, E):
        (keep if float(e @ cen) >= k["outlier_cos"] else drop).append(c)
    if len(keep) >= 3:                                  # tính lại tâm không có ngoại lai rồi kiểm lần nữa
        cen = _unit(np.stack([c["emb"] for c in keep]).mean(axis=0, keepdims=True))[0]
        keep2 = [c for c in keep if float(_unit(c["emb"][None])[0] @ cen) >= k["outlier_cos"]]
        ids2 = {id(c) for c in keep2}
        drop += [c for c in keep if id(c) not in ids2]
        keep = keep2
    return keep, drop


def prune(cands: List[dict], max_n: int, cfg: Optional[dict] = None) -> List[dict]:
    """Giữ tối đa max_n ứng viên trong một nhóm: lần lượt bỏ khung điểm thấp hơn của cặp giống nhau nhất."""
    cands = list(cands)
    while len(cands) > max_n:
        E = _unit(np.stack([c["emb"] for c in cands]))
        S = E @ E.T
        np.fill_diagonal(S, -2)
        i, j = np.unravel_index(int(np.argmax(S)), S.shape)
        cands.pop(i if quality(cands[i], cfg) <= quality(cands[j], cfg) else j)
    return cands


# ---------------------------------------------------------------- chọn tập cuối
def quotas(target: int) -> Dict[str, int]:
    """Phân bổ gợi ý: chính diện ~1/3, 4 hướng còn lại chia đều (24 -> 8 + 4×4)."""
    target = int(max(20, min(30, target)))
    front = int(round(target / 3.0))
    rest = (target - front) // 4
    q = {d: rest for d in posebins.CLUB_DIRS}
    q["front"] = target - rest * 4
    return q


def _pick_diverse(pool: List[dict], n: int, picked: List[dict], cfg: dict) -> List[dict]:
    """Chọn tham lam n khung từ pool: điểm chất lượng nhân hệ số đa dạng (khác embedding và khác góc so với khung đã chọn)."""
    pool = list(pool)
    chosen: List[dict] = []
    ref = list(picked)
    while pool and len(chosen) < n:
        best, best_v = None, -1.0
        for c in pool:
            q = quality(c, cfg)
            if ref:
                e = _unit(c["emb"][None])[0]
                emb_d = min(1.0 - float(e @ _unit(r["emb"][None])[0]) for r in ref)
                pose_d = min(math.hypot((c.get("pitch") or 0) - (r.get("pitch") or 0), (c.get("yaw") or 0) - (r.get("yaw") or 0)) for r in ref)
                if 1.0 - emb_d >= cfg["dup_cos"]:
                    continue
                div = 0.6 * _clamp(emb_d / 0.12) + 0.4 * _clamp(pose_d / 10.0)
            else:
                div = 1.0
            v = q * (0.4 + 0.6 * div)
            if v > best_v:
                best, best_v = c, v
        if best is None:
            break
        chosen.append(best)
        ref.append(best)
        pool = [c for c in pool if c is not best]
    return chosen


def select(cands: Sequence[dict], target: int = 24, cfg: Optional[dict] = None, allow_other: bool = False,
           existing: Optional[Sequence[dict]] = None) -> dict:
    """Chọn tập ảnh gốc 20–30 mẫu, cân bằng theo 5 hướng. `existing`: mẫu gốc đã có của người này (đăng ký bổ sung,
    dict có emb/pitch/yaw): khung trùng hoặc quá giống chúng bị coi là dư. Trả về
    {chosen, per_dir, weak (hướng <min_per_dir), below_min (ít hơn min_real), rejected: {lý do: số}}."""
    k = _c(cfg)
    rej: Dict[str, int] = {}
    ok: List[dict] = []
    for c in cands:
        r = eligible(c, k)
        if r:
            rej[r] = rej.get(r, 0) + 1
        else:
            ok.append(c)
    target = int(max(20, min(30, target)))
    q = quotas(target)
    by_dir: Dict[Optional[str], List[dict]] = {d: [] for d in posebins.CLUB_DIRS}
    by_dir[None] = []
    for c in ok:
        by_dir[c.get("dir") if c.get("dir") in posebins.CLUB_DIRS else None].append(c)
    base = list(existing or [])
    chosen: List[dict] = []
    for d in posebins.CLUB_DIRS:
        chosen += _pick_diverse(by_dir[d], q[d], base + chosen, k)
    # thiếu ở hướng nào thì bù từ hướng còn dư (tối đa 2× hạn mức), rồi (nếu cho phép) từ ảnh ngoài các cửa sổ
    left = target - len(chosen)
    if left > 0:
        chosen_ids = {id(c) for c in chosen}
        pool = [c for d in posebins.CLUB_DIRS for c in by_dir[d] if id(c) not in chosen_ids]
        counts = {d: sum(1 for c in chosen if c.get("dir") == d) for d in posebins.CLUB_DIRS}
        pool = [c for c in pool if counts[c["dir"]] < 2 * q[c["dir"]]]
        chosen += _pick_diverse(pool, left, base + chosen, k)
    left = target - len(chosen)
    if left > 0 and allow_other:
        chosen += _pick_diverse(by_dir[None], left, base + chosen, k)
    per_dir = {d: sum(1 for c in chosen if c.get("dir") == d) for d in posebins.CLUB_DIRS}
    return {"chosen": chosen, "per_dir": per_dir, "weak": [d for d in posebins.CLUB_DIRS if per_dir[d] < k["min_per_dir"]],
            "below_min": len(chosen) < k["min_real"], "rejected": rej, "quotas": q}


# ---------------------------------------------------------------- cần augmentation không?
def consistency(embs: Sequence[np.ndarray]) -> Optional[float]:
    """Trung vị cosine của từng mẫu tới tâm của chính người đó (nội bộ có nhất quán không)."""
    if len(embs) < 3:
        return None
    E = _unit(np.stack(embs))
    cen = _unit(E.mean(axis=0, keepdims=True))[0]
    return float(np.median(E @ cen))


def needs_augment(n_real: int, per_dir: Dict[str, int], cons: Optional[float], cfg: Optional[dict] = None,
                  min_consistency: float = 0.55) -> Tuple[bool, List[str]]:
    """Chỉ augment khi chưa đủ dữ liệu: ít hơn min_real ảnh gốc, hoặc thiếu hướng, hoặc nhất quán nội bộ thấp."""
    k = _c(cfg)
    why = []
    if n_real < k["min_real"]:
        why.append(f"ít ảnh gốc ({n_real}<{k['min_real']})")
    weak = [d for d in posebins.CLUB_DIRS if per_dir.get(d, 0) < k["min_per_dir"]]
    if weak:
        why.append("thiếu hướng: " + ", ".join(posebins.CLUB_LABELS[d] for d in weak))
    if cons is not None and cons < min_consistency:
        why.append(f"nhất quán nội bộ thấp ({cons:.2f})")
    return bool(why), why


KINDS = ("bright", "dark", "rot_p", "rot_n", "scale", "noise", "lowres", "occ_mask", "occ_left", "occ_top", "blur")


def augment_budget(n_real: int, cfg: Optional[dict] = None) -> int:
    """Số bản augment tối đa: ≤ aug_max_ratio × ảnh gốc và tổng ≤ aug_cap_total."""
    k = _c(cfg)
    return max(0, min(int(n_real * k["aug_max_ratio"]), k["aug_cap_total"] - n_real))


def plan_augment(chosen: Sequence[dict], per_dir: Dict[str, int], budget: int, want: int, cfg: Optional[dict] = None) -> List[Tuple[int, str]]:
    """Trả danh sách (chỉ số ảnh gốc, loại augment) dài ≤ min(budget, want). Ưu tiên ảnh thuộc hướng ít mẫu nhất,
    xoay vòng loại augment, mỗi ảnh gốc tối đa 3 biến thể. Thứ tự xác định (tái lập)."""
    n = min(budget, want)
    if n <= 0 or not chosen:
        return []
    order = sorted(range(len(chosen)), key=lambda i: (per_dir.get(chosen[i].get("dir"), 0), -quality(chosen[i], cfg), i))
    out: List[Tuple[int, str]] = []
    used: Dict[int, int] = {}
    ki = 0
    while len(out) < n and any(used.get(i, 0) < 3 for i in order):
        for i in order:
            if len(out) >= n:
                break
            if used.get(i, 0) >= 3:
                continue
            out.append((i, KINDS[ki % len(KINDS)]))
            used[i] = used.get(i, 0) + 1
            ki += 1
    return out


# ---------------------------------------------------------------- kiểm tra sau đăng ký (leave-one-out)
def loo_check(own: np.ndarray, own_dirs: Sequence[Optional[str]], others: Optional[np.ndarray], threshold: float, margin: float) -> dict:
    """Mỗi mẫu gốc của người này: điểm cao nhất tới các mẫu gốc KHÁC của chính họ (genuine) so với điểm cao nhất tới
    người khác (impostor). Đạt khi >=90% mẫu có genuine >= threshold và hơn impostor >= margin."""
    own = _unit(np.asarray(own, dtype=np.float32))
    n = len(own)
    if n < 3:
        return {"ok": False, "n": n, "reason": "too_few", "weak_dirs": [], "advice": "Chưa đủ mẫu để kiểm tra."}
    S = own @ own.T
    np.fill_diagonal(S, -2)
    gen = S.max(axis=1)
    imp = (own @ _unit(others).T).max(axis=1) if others is not None and len(others) else np.full(n, -1.0)
    passed = (gen >= threshold) & (gen - imp >= margin)
    rate = float(passed.mean())
    weak: Dict[str, int] = {}
    for ok_i, d in zip(passed, own_dirs):
        if not ok_i and d:
            weak[d] = weak.get(d, 0) + 1
    weak_dirs = [d for d, _ in sorted(weak.items(), key=lambda kv: -kv[1])]
    ok = rate >= 0.9
    adv = "Đủ tin cậy." if ok else "Nên bổ sung: " + (", ".join(posebins.CLUB_LABELS[d] for d in weak_dirs[:3]) or "thêm ảnh rõ nét")
    return {"ok": ok, "n": n, "pass_rate": round(rate, 3), "genuine_median": round(float(np.median(gen)), 3),
            "genuine_p10": round(float(np.percentile(gen, 10)), 3), "impostor_max": None if others is None or not len(others) else round(float(imp.max()), 3),
            "weak_dirs": weak_dirs, "advice": adv}
