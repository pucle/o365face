"""Bọc InsightFace: phát hiện mặt (kể cả mặt nhỏ), góc đầu, embedding ArcFace, embedding bản lật.

Quy ước góc: xem common/posebins.py (pitch < 0 là cúi, yaw > 0 là quay sang bên phải của ảnh).
Chạy GPU nếu có onnxruntime-gpu, nếu không chạy CPU.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from common.kpspose import pose_from_kps

LITE = os.getenv("LITE_MODE", "0") == "1"      # gói RAM nhỏ (Render free 512 MB)
MAX_SIDE = int(os.getenv("MAX_IMAGE_SIDE", "1280" if LITE else "2560"))   # ảnh lớn hơn sẽ được thu nhỏ trước khi xử lý


@dataclass
class Face:
    bbox: Tuple[int, int, int, int]
    det_score: float
    kps: Optional[np.ndarray]
    pitch: Optional[float] = None
    yaw: Optional[float] = None
    roll: Optional[float] = None
    blur: float = 0.0
    emb: Optional[np.ndarray] = None            # đã chuẩn hoá L2
    emb_flip: Optional[np.ndarray] = None
    occ: dict = field(default_factory=dict)      # tên che khuất -> embedding (mô phỏng bị khuất/che)
    extra: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.bbox[2] - self.bbox[0])

    @property
    def down(self) -> Optional[float]:
        return None if self.pitch is None else -self.pitch

    def brief(self) -> dict:
        r = lambda v: None if v is None else round(float(v), 1)
        return {"bbox": [int(v) for v in self.bbox], "det": round(float(self.det_score), 3),
                "pitch": r(self.pitch), "yaw": r(self.yaw), "roll": r(self.roll),
                "down": r(self.down), "width": self.width, "blur": round(float(self.blur), 1)}


def decode_image(data: bytes) -> Optional[np.ndarray]:
    if not data:
        return None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _blur_score(img: np.ndarray, bbox) -> float:
    """Phương sai Laplacian của vùng mặt đã chuẩn hoá về 96x96: càng cao càng nét."""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return 0.0
    g = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (96, 96), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class FaceEngine:
    def __init__(self, model_name: str = "buffalo_l", det_size: int = 640, det_thresh: float = 0.45,
                 max_concurrency: int = 2):
        import onnxruntime as ort
        from insightface.app import FaceAnalysis

        pose3d = not LITE and os.getenv("POSE_MODE", "3d") == "3d"
        orig_session = ort.InferenceSession
        if LITE:        # 1 luồng, tắt arena/mem-pattern: RAM thấp và ổn định (CPU của gói free rất yếu nên 1 luồng là đủ)
            def lite_session(path, sess_options=None, providers=None, **kw):
                o = ort.SessionOptions()
                o.enable_cpu_mem_arena = False
                o.enable_mem_pattern = False
                o.intra_op_num_threads = 1
                o.inter_op_num_threads = 1
                return orig_session(path, sess_options=o, providers=providers, **kw)
            ort.InferenceSession = lite_session
        avail = ort.get_available_providers()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail] or ["CPUExecutionProvider"]
        self.providers = providers
        self.model_name = model_name
        root = os.getenv("INSIGHTFACE_HOME", "~/.insightface")
        self.app = FaceAnalysis(name=model_name, root=root, providers=providers,
                                allowed_modules=["detection", "recognition"] + (["landmark_3d_68"] if pose3d else []))
        ort.InferenceSession = orig_session
        self.pose_kps = not pose3d
        self.app.prepare(ctx_id=0 if providers[0] == "CUDAExecutionProvider" else -1,
                         det_thresh=det_thresh, det_size=(det_size, det_size))
        self.det = self.app.det_model
        self.rec = self.app.models["recognition"]
        self.lm = self.app.models.get("landmark_3d_68")
        self.default_det_size = det_size
        self._sem = threading.Semaphore(max_concurrency)

    # ------------------------------------------------------------------
    def analyze(self, bgr: np.ndarray, det_size: Optional[int] = None, embed: bool = True,
                flip: bool = False, max_faces: int = 0, occ: bool = False, top: int = 0) -> List[Face]:
        """Phát hiện mặt, ước lượng góc đầu và (tuỳ chọn) embedding. Mặt lớn nhất đứng đầu danh sách.
        top > 0: chỉ ước lượng góc đầu/embedding cho `top` mặt lớn nhất (các mặt còn lại chỉ có khung + điểm tin cậy)."""
        from insightface.app.common import Face as IFace

        size = int(det_size or self.default_det_size)
        # đừng phóng to ảnh nhỏ lên det_size: mặt quá to làm SCRFD bỏ sót
        longest = max(bgr.shape[:2])
        size = max(160, min(size, ((longest + 31) // 32) * 32))
        with self._sem:
            bboxes, kpss = self.det.detect(bgr, input_size=(size, size), max_num=max_faces, metric="default")
            if bboxes is None or bboxes.shape[0] == 0:
                return []
            fimg = cv2.flip(bgr, 1) if (embed and flip) else None
            out: List[Face] = []
            order = np.argsort(-(bboxes[:, 2] - bboxes[:, 0]))
            heavy = set(int(i) for i in (order[:top] if top > 0 else order))
            for i in range(bboxes.shape[0]):
                kps = kpss[i] if kpss is not None else None
                if i not in heavy:                         # mặt nhỏ/phụ: chỉ cần biết có tồn tại
                    out.append(Face(tuple(int(v) for v in bboxes[i, 0:4]), float(bboxes[i, 4]), kps))
                    continue
                f = IFace(bbox=bboxes[i, 0:4], kps=kps, det_score=bboxes[i, 4])
                face = Face(tuple(int(v) for v in bboxes[i, 0:4]), float(bboxes[i, 4]), kps)
                if self.lm is not None:
                    try:
                        self.lm.get(bgr, f)
                        pose = f.pose
                        if pose is not None:
                            face.pitch, face.yaw, face.roll = float(pose[0]), float(pose[1]), float(pose[2])
                    except Exception:                    # góc đầu chỉ là thông tin phụ, không làm hỏng nhận diện
                        pass
                elif self.pose_kps and kps is not None:
                    face.pitch, face.yaw, face.roll = pose_from_kps(kps)
                if embed and kps is not None:
                    self.rec.get(bgr, f)
                    face.emb = _unit(f.embedding)
                    if fimg is not None:
                        w = bgr.shape[1]
                        fk = kps.copy()
                        fk[:, 0] = (w - 1) - fk[:, 0]
                        fk = fk[[1, 0, 2, 4, 3]]            # đổi chỗ mắt trái/phải, mép miệng trái/phải
                        g = IFace(kps=fk)
                        self.rec.get(fimg, g)
                        face.emb_flip = _unit(g.embedding)
                if embed and occ and kps is not None:
                    face.occ = self._occluded(bgr, face, kps)
                face.blur = _blur_score(bgr, face.bbox)
                out.append(face)
        out.sort(key=lambda x: x.width, reverse=True)
        return out

    def embed_face(self, bgr: np.ndarray, face: Face) -> Optional[np.ndarray]:
        """Embedding cho một mặt đã phát hiện (dùng kps có sẵn, không phát hiện lại)."""
        if face.kps is None:
            return None
        return self.embed_with_kps(bgr, face.kps)

    def embed_with_kps(self, bgr: np.ndarray, kps: np.ndarray, flip: bool = False) -> np.ndarray:
        """Embedding từ ảnh + 5 điểm mốc đã biết. flip=True: lật ảnh ngang (và đổi chỗ mắt/mép trái-phải) rồi tính."""
        from insightface.app.common import Face as IFace
        kps = np.asarray(kps, dtype=np.float32).copy()
        img = bgr
        if flip:
            img = cv2.flip(bgr, 1)
            kps[:, 0] = (bgr.shape[1] - 1) - kps[:, 0]
            kps = kps[[1, 0, 2, 4, 3]]
        with self._sem:
            g = IFace(kps=kps)
            self.rec.get(img, g)
        return _unit(g.embedding)

    def warmup(self, det_size: int = 640) -> float:
        """Chạy thử một lượt để nạp model vào bộ nhớ nóng (lần gọi thật đầu tiên không bị chậm). Trả về số giây."""
        import time
        from insightface.app.common import Face as IFace
        t0 = time.time()
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (det_size, det_size, 3), dtype=np.uint8)
        with self._sem:
            self.det.detect(img, input_size=(det_size, det_size), max_num=0, metric="default")
            kps = np.array([[240, 250], [400, 250], [320, 330], [260, 410], [380, 410]], dtype=np.float32)
            f = IFace(bbox=np.array([200, 180, 440, 460], dtype=np.float32), kps=kps, det_score=0.9)
            self.rec.get(img, f)
            if self.lm is not None:
                try:
                    self.lm.get(img, f)
                except Exception:
                    pass
        return time.time() - t0

    OCC_KINDS = ("mask", "left", "right", "top")

    def _occluded(self, bgr: np.ndarray, face: Face, kps: np.ndarray) -> dict:
        """Embedding của chính khuôn mặt này khi bị che một phần (khẩu trang/tay, che nửa trái/phải, tóc che mắt).
        Giúp nhận ra người ngồi bị khuất một phần. Đo thực tế: điểm cùng người vẫn >> điểm người khác."""
        from insightface.app.common import Face as IFace
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        w, h = x2 - x1, y2 - y1
        out = {}
        for kind in self.OCC_KINDS:
            o = bgr.copy()
            if kind == "mask":
                o[int(y1 + .52 * h):y2 + 5, max(0, x1 - 5):x2 + 5] = (150, 150, 150)
            elif kind == "left":
                o[max(0, y1 - 5):y2 + 5, max(0, x1 - 5):int(x1 + .45 * w)] = (120, 120, 120)
            elif kind == "right":
                o[max(0, y1 - 5):y2 + 5, int(x1 + .55 * w):x2 + 5] = (120, 120, 120)
            else:
                o[max(0, y1 - 5):int(y1 + .35 * h), max(0, x1 - 5):x2 + 5] = (60, 60, 60)
            g = IFace(kps=kps)
            self.rec.get(o, g)
            out[kind] = _unit(g.embedding)
        return out

    def best_face(self, bgr: np.ndarray, **kw) -> Optional[Face]:
        fs = self.analyze(bgr, **kw)
        if not fs:                      # mặt quá to so với det_size (cận cảnh) -> thử lại ở độ phân giải thấp
            for small in (480, 320):
                if max(bgr.shape[:2]) > small and small < int(kw.get("det_size") or self.default_det_size):
                    kw2 = dict(kw, det_size=small)
                    fs = self.analyze(bgr, **kw2)
                    if fs:
                        break
        return fs[0] if fs else None

    def analyze_crop(self, crop: np.ndarray, min_side: int = 320, det_size: int = 640, **kw) -> List[Face]:
        """Mặt trong ảnh cắt nhỏ (ví dụ phần đầu-vai của một người từ cam trần): phóng to rồi phát hiện."""
        h, w = crop.shape[:2]
        if min(h, w) < min_side:
            s = min_side / max(1, min(h, w))
            crop = cv2.resize(crop, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
        return self.analyze(crop, det_size=det_size, **kw)
