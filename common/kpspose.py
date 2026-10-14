"""Ước lượng góc đầu chỉ từ 5 điểm mốc của bộ phát hiện (mắt, mũi, hai mép miệng) — dùng khi KHÔNG nạp model landmark_3d_68
(model này tốn thêm ~350 MB RAM, không vừa gói free 512 MB của Render).

Cùng quy ước với common/posebins.py: pitch > 0 ngẩng, yaw > 0 cùng chiều với InsightFace 3D (đã đối chiếu dấu trên vài ảnh thật).
Đây là ước lượng HÌNH HỌC thô: yaw khá ổn (độ lệch mũi so với trục đối xứng mắt-miệng), pitch kém chính xác hơn.
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

YAW_NOSE_LEN = 0.55      # độ nhô của mũi so với khoảng cách hai mắt (hệ số của asin)
PITCH_R0 = 0.55          # tỉ lệ vị trí mũi giữa mắt và miệng khi nhìn thẳng
PITCH_GAIN = 150.0       # độ / đơn vị tỉ lệ


def pose_from_kps(kps) -> Tuple[float, float, float]:
    k = np.asarray(kps, dtype=np.float64).reshape(5, 2)
    le, re_, nose, lm, rm = k
    axis = re_ - le
    d = float(np.linalg.norm(axis))
    if d < 1e-6:
        return 0.0, 0.0, 0.0
    u = axis / d
    v = np.array([-u[1], u[0]])                         # vuông góc với đường hai mắt (hướng xuống ảnh)
    eye_mid, mouth_mid = (le + re_) / 2, (lm + rm) / 2
    mid = (eye_mid + mouth_mid) / 2
    off = float(np.dot(nose - mid, u)) / d
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, off / YAW_NOSE_LEN))))
    span = float(np.dot(mouth_mid - eye_mid, v))
    r = float(np.dot(nose - eye_mid, v)) / span if abs(span) > 1e-6 else PITCH_R0
    pitch = max(-60.0, min(60.0, (PITCH_R0 - r) * PITCH_GAIN))
    roll = math.degrees(math.atan2(axis[1], axis[0]))
    return pitch, yaw, roll
