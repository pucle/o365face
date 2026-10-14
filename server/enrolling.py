"""Đăng ký khuôn mặt kiểu CLB theo phiên: mỗi khung hình được xử lý đúng MỘT lần trên server (phát hiện + góc + embedding),
ứng viên tốt nằm trong RAM của phiên (có TTL), khi kết thúc mới chọn 20–30 mẫu và ghi DB một lần.
Không ghi ảnh ra đĩa/DB: ảnh chỉ nằm trong RAM của phiên để tính embedding bản lật/augmentation cho đúng các mẫu đã chọn.
"""
from __future__ import annotations

import threading
import os
import time
import uuid
from collections import Counter
from typing import Dict, List, Optional

import cv2
import numpy as np

from common import enrollselect as es
from common import posebins
from . import augment

POOL_CAP_LIVE = 30
POOL_CAP_DATASET = 40
LITE = os.getenv("LITE_MODE", "0") == "1"   # gói RAM nhỏ: ít phiên, ảnh tạm nhỏ hơn (mỗi ứng viên giữ một ảnh JPEG trong RAM)
MAX_SESSIONS = 2 if LITE else 8
SESSION_TTL_S = (10 if LITE else 20) * 60
POOL_MAX_SIDE = 640 if LITE else 960
JPEG_Q = 80 if LITE else 88
LOOKS_LIKE_OTHER = 0.5


# ---------------------------------------------------------------- phiên
class Session:
    def __init__(self, member_id: str, name: str, mode: str, kind: str, source: str):
        self.sid = uuid.uuid4().hex[:16]
        self.member_id, self.name, self.mode, self.kind, self.source = member_id, name, mode, kind, source
        self.created = self.touched = time.time()
        self.pool: Dict[Optional[str], List[dict]] = {d: [] for d in (*posebins.CLUB_DIRS, None)}
        self.seq = 0
        self.frames = 0
        self.rejects: Counter = Counter()
        self.pending: Optional[dict] = None
        self.lock = threading.RLock()

    @property
    def cap(self) -> int:
        return POOL_CAP_DATASET if self.kind == "dataset" else POOL_CAP_LIVE

    def counts(self) -> Dict[str, int]:
        return {(d or "other"): len(v) for d, v in self.pool.items()}

    def total(self) -> int:
        return sum(len(v) for v in self.pool.values())

    def add(self, cand: dict, cfg: dict) -> bool:
        """Thêm ứng viên vào nhóm hướng của nó; nhóm đầy thì bỏ khung kém nhất/trùng nhất. Trả về True nếu khung còn trong nhóm."""
        with self.lock:
            self.seq += 1
            cand["fid"] = self.seq
            d = cand.get("dir")
            bucket = self.pool[d if d in self.pool else None]
            bucket.append(cand)
            if len(bucket) > self.cap:
                kept = es.prune(bucket, self.cap, cfg)
                bucket[:] = kept
                self.pending = None
                return any(c is cand for c in kept)
            self.pending = None
            return True

    def reset(self, direction: Optional[str] = None) -> None:
        with self.lock:
            for d in self.pool:
                if direction is None or d == direction:
                    self.pool[d] = []
            self.pending = None

    def all(self) -> List[dict]:
        with self.lock:
            return [c for v in self.pool.values() for c in v]

    def centroid(self) -> Optional[np.ndarray]:
        cs = self.all()
        if not cs:
            return None
        m = np.stack([c["emb"] for c in cs]).mean(axis=0)
        n = np.linalg.norm(m)
        return m / n if n else m


class SessionStore:
    def __init__(self, ttl: float = SESSION_TTL_S, max_sessions: int = MAX_SESSIONS):
        self.ttl, self.max = ttl, max_sessions
        self.items: Dict[str, Session] = {}
        self.lock = threading.Lock()

    def sweep(self, now: Optional[float] = None) -> int:
        now = now or time.time()
        with self.lock:
            dead = [k for k, s in self.items.items() if now - s.touched > self.ttl]
            for k in dead:
                del self.items[k]
            return len(dead)

    def create(self, *a, **kw) -> Session:
        self.sweep()
        s = Session(*a, **kw)
        with self.lock:
            while len(self.items) >= self.max:                       # đầy: bỏ phiên cũ nhất
                oldest = min(self.items.values(), key=lambda x: x.touched)
                del self.items[oldest.sid]
            self.items[s.sid] = s
        return s

    def get(self, sid: str) -> Optional[Session]:
        self.sweep()
        with self.lock:
            s = self.items.get(sid)
        if s:
            s.touched = time.time()
        return s

    def clear(self) -> int:
        with self.lock:
            n = len(self.items)
            self.items.clear()
            return n

    def delete(self, sid: str) -> bool:
        with self.lock:
            return self.items.pop(sid, None) is not None


# ---------------------------------------------------------------- một khung hình
def normalize(img: np.ndarray, max_side: int = POOL_MAX_SIDE) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img
    s = max_side / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


REASON_STATE = {"multiple_faces": "multi", "clipped": "clipped", "low_det": "unsure", "small": "far", "blurry": "blurry"}


def observe(engine, img: np.ndarray, cfg: dict, det_size: int, keep_other: bool = False, embed: bool = True):
    """Phân tích một khung. Trả về (info, cand|None). info['state']: ok | no_face | multi | clipped | unsure | far | blurry | between.
    Chỉ tính embedding khi khung đã qua cổng chất lượng và nằm trong cửa sổ một hướng (hoặc keep_other)."""
    img = normalize(img)
    H, W = img.shape[:2]
    faces = engine.analyze(img, det_size=det_size, embed=False, top=1)
    if not faces:
        return {"state": "no_face", "w": W, "h": H}, None
    f = faces[0]
    big = sum(1 for x in faces if x.width >= 0.6 * f.width)
    x1, y1, x2, y2 = f.bbox
    cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
    light = float(cv2.cvtColor(img[cy1:cy2, cx1:cx2], cv2.COLOR_BGR2GRAY).mean()) if cx2 - cx1 > 4 and cy2 - cy1 > 4 else 128.0
    m = 0.08 * f.width
    clipped = x1 < -m or y1 < -m or x2 > W + m or y2 > H + m
    d = posebins.club_dir(f.pitch, f.yaw)
    cand = dict(dir=d, pitch=f.pitch, yaw=f.yaw, det=float(f.det_score), width=f.width, blur=float(f.blur), light=light,
                clipped=clipped, nfaces=big, emb=None, kps=f.kps, bbox=tuple(int(v) for v in f.bbox))
    info = {"state": "ok", "dir": d, "pitch": None if f.pitch is None else round(f.pitch, 1),
            "yaw": None if f.yaw is None else round(f.yaw, 1), "width": f.width, "det": round(float(f.det_score), 2),
            "blur": round(float(f.blur), 1), "light": round(light), "faces": big, "w": W, "h": H,
            "box": [round(max(0, x1) / W, 4), round(max(0, y1) / H, 4), round(min(W, x2) / W, 4), round(min(H, y2) / H, 4)]}
    r = es.eligible(cand, cfg, need_emb=False)
    if r:
        info["state"] = REASON_STATE.get(r, r)
        return info, None
    if f.kps is None or f.pitch is None:
        info["state"] = "no_face"
        return info, None
    if d is None and not keep_other:
        info["state"] = "between"
        return info, None
    if not embed:
        return info, None
    cand["emb"] = engine.embed_face(img, f)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    cand["jpg"] = buf.tobytes() if ok else b""
    return info, cand


# ---------------------------------------------------------------- kiểm tra giống thành viên khác
def other_scores(embs: np.ndarray, other_mat: np.ndarray, other_ids: List[str]):
    """Với mỗi mẫu: (điểm cao nhất tới thành viên khác, id người đó)."""
    if other_mat is None or not len(other_mat):
        return np.full(len(embs), -1.0), [None] * len(embs)
    S = embs @ other_mat.T
    j = S.argmax(axis=1)
    return S.max(axis=1), [other_ids[i] for i in j]


# ---------------------------------------------------------------- chốt phiên
def build_plan(sess: Session, engine, cfg: dict, own: List[dict], other_mat: np.ndarray, other_ids: List[str],
               names: Dict[str, str], opts: dict, max_images: int, thr: float, margin: float) -> dict:
    """Chọn mẫu và tính mọi embedding cần ghi, CHƯA ghi DB. `own`: mẫu của người này đã có (dict: emb, pitch, yaw, step, img).
    opts: target, flip, augment ('auto'|'off'|'force'), verify."""
    k = dict(cfg)
    k["target"] = int(opts.get("target") or cfg["target"])
    replace = sess.mode == "replace"
    own_real = [] if replace else [o for o in own if "+" not in (o.get("step") or "") and o.get("pitch") is not None]
    own_imgs = 0 if replace else len({o["img"] for o in own})
    cands = sess.all()
    rejected: Counter = Counter({r: n for r, n in sess.rejects.items()})
    warnings: List[str] = []
    n_in = len(cands)

    # 1) giống thành viên khác hơn chính người này -> bỏ (chọn nhầm người / bỏ nhầm thư mục)
    if opts.get("verify", True) and cands and len(other_mat):
        E = np.stack([c["emb"] for c in cands])
        osc, oid = other_scores(E, other_mat, other_ids)
        own_best = (E @ np.stack([o["emb"] for o in own_real]).T).max(axis=1) if own_real else np.full(len(cands), -1.0)
        keep = []
        for c, so, who, sw in zip(cands, osc, oid, own_best):
            if so >= LOOKS_LIKE_OTHER and so > sw + 0.1:
                rejected["looks_like_other"] += 1
                if len(warnings) < 3:
                    warnings.append(f"Có khung giống {names.get(who, who)} ({so:.2f}) hơn {sess.name or sess.member_id}. Có chọn nhầm người không?")
            else:
                keep.append(c)
        cands = keep

    # 2) loại ngoại lai so với tâm của phiên (+ mẫu cũ khi đăng ký bổ sung)
    cands, dropped = es.drop_outliers(cands, k, extra_ref=np.stack([o["emb"] for o in own_real]) if own_real else None)
    if dropped:
        rejected["outlier"] += len(dropped)

    existing = [{"emb": o["emb"], "pitch": o["pitch"], "yaw": o["yaw"]} for o in own_real]
    sel = es.select(cands, k["target"], k, allow_other=(sess.kind == "dataset"), existing=existing)
    for r, n in sel["rejected"].items():
        rejected[r] += n
    chosen = sel["chosen"][:max(0, max_images - own_imgs)]
    report = {"member_id": sess.member_id, "mode": sess.mode, "kind": sess.kind, "target": k["target"], "candidates": n_in,
              "rejected": dict(rejected), "warnings": warnings, "existing_real": len(own_real)}
    if not chosen:
        why = "Chưa có khung nào dùng được."
        if rejected.get("looks_like_other"):
            why = "Các khung giống thành viên khác hơn người này: kiểm tra đã chọn đúng người chưa."
        elif n_in == 0:
            why = "Chưa nhận được khung hình có mặt nào: kiểm tra camera/ánh sáng và quay đủ các hướng."
        report.update(kept=0, per_dir={d: 0 for d in posebins.CLUB_DIRS}, weak=list(posebins.CLUB_DIRS), flips=0, aug=0,
                      verdict="Chưa lưu được", advice=why, chosen=[], ok=False)
        return {"report": report, "rows": [], "replace": replace}

    # 3) bản lật + (khi thiếu dữ liệu) augmentation, chỉ cho các ảnh đã chọn
    imgs = {c["fid"]: cv2.imdecode(np.frombuffer(c["jpg"], np.uint8), cv2.IMREAD_COLOR) for c in chosen}
    for c in chosen:
        c["img_id"] = uuid.uuid4().hex[:12]
    flips = {}
    if opts.get("flip", True):
        for c in chosen:
            if imgs[c["fid"]] is not None:
                flips[c["fid"]] = engine.embed_with_kps(imgs[c["fid"]], c["kps"], flip=True)

    per_dir_tot = {d: sel["per_dir"][d] + sum(1 for o in own_real if posebins.club_dir(o["pitch"], o["yaw"]) == d) for d in posebins.CLUB_DIRS}
    n_real = len(own_real) + len(chosen)
    cons = es.consistency([o["emb"] for o in own_real] + [c["emb"] for c in chosen])
    mode_aug = opts.get("augment") or "auto"
    need, why = es.needs_augment(n_real, per_dir_tot, cons, k)
    if mode_aug == "force":
        need = True
    if mode_aug == "auto" and sess.kind != "dataset":
        need = False                                     # đăng ký trực tiếp: không augment, bảo người dùng quay thêm
    augs: List[dict] = []
    aug_drop: Counter = Counter()
    if need and mode_aug != "off":
        budget = es.augment_budget(n_real, k)
        for idx, kind in es.plan_augment(chosen, per_dir_tot, budget, budget, k):
            c = chosen[idx]
            im = imgs[c["fid"]]
            if im is None:
                continue
            im2, kp2 = augment.apply(im, c["kps"], c["bbox"], kind, augment.seed_for(sess.member_id, c["fid"], kind))
            e2 = engine.embed_with_kps(im2, kp2)
            if float(e2 @ c["emb"]) < k["aug_min_cos"]:
                aug_drop["low_cos"] += 1
                continue
            if len(other_mat) and float((other_mat @ e2).max()) >= LOOKS_LIKE_OTHER:
                aug_drop["looks_like_other"] += 1
                continue
            augs.append({"src": c, "kind": kind, "emb": e2})

    # 4) hàng cần ghi + kiểm tra leave-one-out
    rows = []
    for c in chosen:
        d = c.get("dir") or "other"
        rows.append({"emb": c["emb"], "pitch": c["pitch"], "yaw": c["yaw"], "img": c["img_id"], "step": "club-" + d})
        if c["fid"] in flips:
            rows.append({"emb": flips[c["fid"]], "pitch": c["pitch"], "yaw": -c["yaw"], "img": c["img_id"], "step": f"club-{d}+flip"})
    for a in augs:
        c = a["src"]
        rows.append({"emb": a["emb"], "pitch": c["pitch"], "yaw": c["yaw"], "img": c["img_id"],
                     "step": f"club-{c.get('dir') or 'other'}+aug-{a['kind']}"})
    real_embs = np.stack([o["emb"] for o in own_real] + [c["emb"] for c in chosen])
    real_dirs = [posebins.club_dir(o["pitch"], o["yaw"]) for o in own_real] + [c.get("dir") for c in chosen]
    check = es.loo_check(real_embs, real_dirs, other_mat if len(other_mat) else None, thr, margin)
    weak = [d for d in posebins.CLUB_DIRS if per_dir_tot[d] < k["min_per_dir"]]
    bad = list(dict.fromkeys(weak + list(check.get("weak_dirs", []))))
    low = n_real < k["min_real"]
    ok = not weak and not low and check.get("ok", False)
    if ok:
        verdict, advice = "Đủ tin cậy", "Đủ mẫu ở cả 5 hướng."
    else:
        parts = [posebins.CLUB_LABELS[d] for d in bad[:3]]
        verdict = "Nên bổ sung: " + ", ".join(parts) if parts else "Nên bổ sung thêm ảnh rõ nét"
        advice = (f"Mới có {n_real}/{k['min_real']} mẫu gốc. " if low else "") + "Chọn 'Làm lại hướng yếu' hoặc đăng ký lại để bổ sung."
    report.update(kept=len(chosen), per_dir=sel["per_dir"], per_dir_total=per_dir_tot, weak=weak, flips=len(flips), aug=len(augs),
                  aug_dropped=dict(aug_drop), augment_reasons=why if need else [], augmented=bool(need and mode_aug != "off"),
                  consistency=None if cons is None else round(cons, 3), total_real=n_real, check=check, verdict=verdict,
                  advice=advice, ok=bool(ok), below_min=low,
                  chosen=[{"fid": c["fid"], "dir": c.get("dir"), "pitch": round(c["pitch"], 1), "yaw": round(c["yaw"], 1),
                           "q": round(es.quality(c, k), 2)} for c in chosen])
    if len(chosen) < len(sel["chosen"]):
        report["warnings"].append("Đã đạt giới hạn số ảnh cho một người, một số mẫu không được lưu.")
    return {"report": report, "rows": rows, "replace": replace}
