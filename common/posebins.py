"""Quy ước góc đầu và "độ phủ góc" của mẫu khuôn mặt đã đăng ký.

Quy ước (khớp InsightFace 0.7.3, đã kiểm chứng trên ảnh thật):
    pitch < 0  : cúi đầu (mặt hướng xuống)        ->  down = -pitch
    pitch > 0  : ngẩng đầu
    yaw   > 0  : mặt quay sang bên PHẢI CỦA ẢNH  = bên TRÁI của chính người đó khi nhìn vào camera
    yaw   < 0  : mặt quay sang bên TRÁI CỦA ẢNH  = bên PHẢI của người đó

Camera đặt trên cao thấy mặt theo kiểu "cúi nhiều" (down lớn) dù người đó đang ngồi thẳng.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

YAW_EDGES = (-30.0, -12.0, 12.0, 30.0)
YAW_NAMES = ("R2", "R1", "C", "L1", "L2")
YAW_LABELS = {"R2": "Phải sâu", "R1": "Phải", "C": "Thẳng", "L1": "Trái", "L2": "Trái sâu"}

DOWN_EDGES = (-8.0, 12.0, 28.0)           # theo "down" = -pitch
PITCH_NAMES = ("up", "level", "down1", "down2")
PITCH_LABELS = {"up": "Ngẩng", "level": "Ngang", "down1": "Cúi nhẹ", "down2": "Cúi nhiều"}

# Các ô cần phủ cho từng nơi dùng
PROFILES: Dict[str, List[Tuple[str, str]]] = {
    "door": [("level", "C"), ("level", "L1"), ("level", "R1"), ("down1", "C"), ("up", "C")],
    "room": [("down1", "C"), ("down1", "L1"), ("down1", "R1"),
             ("down2", "C"), ("down2", "L1"), ("down2", "R1")],
}


def to_view(pitch: float, yaw: float) -> Tuple[float, float]:
    """(pitch, yaw) của InsightFace -> (down, left): down>0 là cúi, left>0 là quay sang trái của người đó."""
    return -float(pitch), float(yaw)


def _bin(value: float, edges: Tuple[float, ...]) -> int:
    for i, e in enumerate(edges):
        if value < e:
            return i
    return len(edges)


def bin_of(pitch: float, yaw: float) -> Tuple[str, str]:
    down, _ = to_view(pitch, yaw)
    return PITCH_NAMES[_bin(down, DOWN_EDGES)], YAW_NAMES[_bin(float(yaw), YAW_EDGES)]


def is_high_angle(pitch: float, yaw: float, high_pitch: float = 22.0, high_yaw: float = 40.0) -> bool:
    """True nếu mặt bị nhìn từ trên cao (cúi nhiều) hoặc xoay nghiêng nhiều."""
    return (-float(pitch)) >= high_pitch or abs(float(yaw)) >= high_yaw


def coverage(items: Iterable[Tuple[float, float]]) -> Dict[str, object]:
    """items: các cặp (pitch, yaw). Trả về lưới đếm theo [pitch_bin][yaw_bin] và tổng số."""
    grid = {p: {y: 0 for y in YAW_NAMES} for p in PITCH_NAMES}
    n = 0
    for pitch, yaw in items:
        if pitch is None or yaw is None:
            continue
        p, y = bin_of(pitch, yaw)
        grid[p][y] += 1
        n += 1
    return {"grid": grid, "total": n}


def missing(cov: Dict[str, object], profile: str, min_per_cell: int = 1) -> List[Tuple[str, str]]:
    grid = cov["grid"]  # type: ignore[index]
    return [(p, y) for p, y in PROFILES[profile] if grid[p][y] < min_per_cell]


def score(cov: Dict[str, object], profile: str, min_per_cell: int = 1) -> float:
    cells = PROFILES[profile]
    if not cells:
        return 1.0
    return 1.0 - len(missing(cov, profile, min_per_cell)) / len(cells)


def cell_label(p: str, y: str) -> str:
    return f"{PITCH_LABELS[p]} · {YAW_LABELS[y]}"


# ----------------------------------------------------------------------------------------------
# Profile "club": 5 tư thế theo hướng dẫn của CLB: nhìn chính diện, quay trái/phải ~45°, ngẩng/cúi ~45°.
# Quy ước InsightFace như trên: pitch>0 ngẩng, pitch<0 cúi, yaw>0 = quay sang TRÁI của chính người đó.
# Cửa sổ rộng hơn 45° một chút vì góc ước lượng ở xa chính diện kém ổn định.
CLUB_DIRS = ("front", "left", "right", "up", "down")
CLUB_LABELS = {"front": "Chính diện", "left": "Quay trái 45°", "right": "Quay phải 45°", "up": "Ngẩng 45°", "down": "Cúi 45°"}
# (pitch_min, pitch_max, yaw_min, yaw_max)
CLUB_WINDOWS = {
    "front": (-12.0, 12.0, -14.0, 14.0),
    "left": (-25.0, 25.0, 28.0, 75.0),
    "right": (-25.0, 25.0, -75.0, -28.0),
    "up": (15.0, 65.0, -27.0, 27.0),
    "down": (-65.0, -15.0, -27.0, 27.0),
}
CLUB_TARGETS = {"front": (0.0, 0.0), "left": (0.0, 45.0), "right": (0.0, -45.0), "up": (30.0, 0.0), "down": (-30.0, 0.0)}   # (pitch, yaw)


def club_dir(pitch: Optional[float], yaw: Optional[float]) -> Optional[str]:
    """Hướng CLB mà góc (pitch, yaw) thuộc về, hoặc None nếu nằm giữa các hướng."""
    if pitch is None or yaw is None:
        return None
    for d in CLUB_DIRS:
        p0, p1, y0, y1 = CLUB_WINDOWS[d]
        if p0 <= pitch <= p1 and y0 <= yaw <= y1:
            return d
    return None


def club_counts(items: Iterable[Tuple[float, float]]) -> Dict[str, int]:
    out = {d: 0 for d in CLUB_DIRS}
    for pitch, yaw in items:
        d = club_dir(pitch, yaw)
        if d:
            out[d] += 1
    return out


def club_missing(counts: Dict[str, int], min_per_dir: int = 2) -> List[str]:
    return [d for d in CLUB_DIRS if counts.get(d, 0) < min_per_dir]
