"""Augmentation ảnh khuôn mặt cho dataset thiếu mẫu. Chỉ biến đổi NHẸ, giống điều kiện thật của cam cửa/cam trần:
đổi sáng/tối, xoay nhỏ (roll), dịch/phóng nhẹ, nhiễu + nén JPEG, mờ/xa (thu nhỏ rồi phóng lại), che một phần.
Không bẻ hình học mạnh để "giả" góc quay; không chỉnh trực tiếp vector embedding.

apply(img, kps, bbox, kind, seed) -> (ảnh mới, kps mới). Cùng (kind, seed) cho cùng kết quả.
"""
from __future__ import annotations

import zlib
from typing import Tuple

import cv2
import numpy as np

KINDS = ("bright", "dark", "rot_p", "rot_n", "scale", "noise", "lowres", "occ_mask", "occ_left", "occ_top", "blur")


def seed_for(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode("utf-8")) & 0x7FFFFFFF


def _affine_pts(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.asarray(pts, dtype=np.float32)
    return (p @ m[:, :2].T + m[:, 2]).astype(np.float32)


def _warp(img, m):
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def apply(img: np.ndarray, kps: np.ndarray, bbox, kind: str, seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    if kind not in KINDS:
        raise ValueError(f"augmentation không hỗ trợ: {kind}")
    rng = np.random.default_rng(seed)
    kps = np.asarray(kps, dtype=np.float32).copy()
    x1, y1, x2, y2 = [int(v) for v in bbox]
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    H, W = img.shape[:2]
    out = img
    if kind == "bright":
        a, b = 1.0 + rng.uniform(0.0, 0.15), rng.uniform(25, 45)
        out = cv2.convertScaleAbs(img, alpha=a, beta=b)
    elif kind == "dark":
        g = rng.uniform(1.4, 1.9)
        lut = (np.linspace(0, 1, 256) ** g * 255).astype(np.uint8)
        out = cv2.convertScaleAbs(cv2.LUT(img, lut), alpha=rng.uniform(0.8, 0.95), beta=0)
    elif kind in ("rot_p", "rot_n"):
        ang = rng.uniform(5, 10) * (1 if kind == "rot_p" else -1)
        m = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
        out, kps = _warp(img, m), _affine_pts(m, kps)
    elif kind == "scale":
        s = rng.uniform(0.92, 1.08)
        dx, dy = rng.uniform(-0.05, 0.05) * w, rng.uniform(-0.05, 0.05) * h
        m = np.array([[s, 0, cx - s * cx + dx], [0, s, cy - s * cy + dy]], dtype=np.float32)
        out, kps = _warp(img, m), _affine_pts(m, kps)
    elif kind == "noise":
        n = rng.normal(0, rng.uniform(6, 10), img.shape).astype(np.float32)
        noisy = np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)
        ok, buf = cv2.imencode(".jpg", noisy, [cv2.IMWRITE_JPEG_QUALITY, 50])
        out = cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else noisy
    elif kind == "lowres":
        f = rng.uniform(0.35, 0.5)
        small = cv2.resize(img, (max(8, int(W * f)), max(8, int(H * f))), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
    elif kind == "blur":
        k = int(rng.choice([3, 5]))
        out = cv2.GaussianBlur(img, (k, k), 0)
    else:                                            # che một phần (giống engine._occluded)
        out = img.copy()
        if kind == "occ_mask":
            out[int(y1 + .52 * h):y2 + 5, max(0, x1 - 5):x2 + 5] = (150, 150, 150)
        elif kind == "occ_left":
            out[max(0, y1 - 5):y2 + 5, max(0, x1 - 5):int(x1 + .45 * w)] = (120, 120, 120)
        else:
            out[max(0, y1 - 5):int(y1 + .35 * h), max(0, x1 - 5):x2 + 5] = (60, 60, 60)
    return out, kps
