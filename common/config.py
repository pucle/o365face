"""Cấu hình mặc định + kiểm tra giá trị. Các giá trị chỉnh trong giao diện được lưu vào DB (bảng settings)
và áp dụng ngay, không cần khởi động lại server."""
from __future__ import annotations

import os
from typing import Any, Dict

# key: (mặc định, kiểu, min, max, mô tả)
SPEC: Dict[str, tuple] = {
    "door_threshold":   (0.45, float, 0.20, 0.90, "Cosine tối thiểu để nhận check-in ở cam cửa"),
    "door_margin":      (0.08, float, 0.00, 0.50, "Chênh lệch tối thiểu giữa người giống nhất và người thứ hai (cam cửa)"),
    "door_votes":       (3, int, 1, 10, "Số khung hình trong một burst phải cùng ra một người"),
    "room_threshold":   (0.42, float, 0.20, 0.90, "Cosine tối thiểu ở cam phòng (mặt nhìn tương đối thẳng)"),
    "room_threshold_high": (0.38, float, 0.20, 0.90, "Cosine tối thiểu ở cam phòng khi mặt nhìn từ trên cao hoặc nghiêng nhiều"),
    "room_margin":      (0.06, float, 0.00, 0.50, "Chênh lệch tối thiểu giữa người thứ nhất và thứ hai (cam phòng)"),
    "room_votes":       (2, int, 1, 10, "Số lần nhận cùng một người trên một track mới gán danh tính"),
    "high_angle_pitch": (22.0, float, 5.0, 80.0, "Từ góc cúi (độ) này trở lên coi là nhìn từ trên cao"),
    "high_angle_yaw":   (40.0, float, 10.0, 90.0, "Từ góc xoay (độ) này trở lên coi là nghiêng nhiều"),
    "grace_s":          (120, int, 10, 3600, "Số giây không thấy mới tính là rời phòng"),
    "min_absence_s":    (60, int, 0, 3600, "Khoảng vắng ngắn hơn số giây này bị bỏ qua"),
    "open_hour":        (8, int, 0, 23, "Giờ mở cửa (giờ địa phương)"),
    "close_hour":       (20, int, 1, 24, "Giờ đóng cửa (giờ địa phương)"),
    "det_size_door":    (640, int, 320, 1920, "Kích thước phát hiện mặt cho cam cửa"),
    "det_size_room":    (960, int, 320, 1920, "Kích thước phát hiện mặt cho cam phòng (lớn hơn để thấy mặt nhỏ)"),
    "det_size_enroll":  (320, int, 256, 1280, "Kích thước phát hiện mặt khi đăng ký bằng camera (mặt gần nên nhỏ cũng đủ; nhỏ hơn thì nhanh hơn)"),
    "enroll_target":    (24, int, 20, 30, "Số mẫu ảnh gốc giữ lại cho mỗi người khi đăng ký kiểu CLB"),
    "enroll_min_per_dir": (2, int, 1, 8, "Số mẫu tối thiểu cho mỗi hướng (chính diện, trái, phải, ngẩng, cúi)"),
    "enroll_min_real":  (20, int, 5, 30, "Ít hơn số mẫu gốc này thì coi là chưa đủ (dataset: bật augmentation)"),
    "enroll_min_det":   (0.55, float, 0.2, 0.95, "Độ tin cậy phát hiện mặt tối thiểu của một mẫu"),
    "enroll_min_width": (70, int, 20, 400, "Chiều rộng mặt tối thiểu (pixel, ảnh gửi lên) của một mẫu"),
    "enroll_min_blur":  (12.0, float, 0.0, 200.0, "Độ nét tối thiểu (phương sai Laplacian vùng mặt) của một mẫu"),
    "enroll_outlier_cos": (0.30, float, 0.0, 0.9, "Mẫu có cosine tới tâm của phiên thấp hơn mức này bị coi là người khác/nhận nhầm"),
    "enroll_w_det":     (0.15, float, 0.0, 1.0, "Trọng số điểm: độ tin cậy phát hiện"),
    "enroll_w_size":    (0.15, float, 0.0, 1.0, "Trọng số điểm: kích thước mặt"),
    "enroll_w_blur":    (0.25, float, 0.0, 1.0, "Trọng số điểm: độ nét"),
    "enroll_w_light":   (0.10, float, 0.0, 1.0, "Trọng số điểm: ánh sáng"),
    "enroll_w_pose":    (0.35, float, 0.0, 1.0, "Trọng số điểm: gần góc đích của hướng"),
    "aug_min_cos":      (0.60, float, 0.2, 0.95, "Bản augmentation có cosine với ảnh gốc thấp hơn mức này bị bỏ"),
    "aug_max_ratio":    (0.5, float, 0.0, 1.0, "Số bản augmentation tối đa so với số mẫu gốc"),
    "aug_cap_total":    (60, int, 20, 150, "Tổng mẫu (gốc + augmentation) tối đa cho một người"),
}

ENV_OVERRIDES = {
    "door_threshold": "CHECKIN_THRESHOLD",
    "door_margin": "CHECKIN_MARGIN",
    "door_votes": "CHECKIN_VOTES",
    "room_threshold": "ROOM_THRESHOLD",
    "grace_s": "GRACE_S",
    "min_absence_s": "MIN_ABSENCE_S",
}


def defaults() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, (d, typ, lo, hi, _) in SPEC.items():
        v = d
        env = ENV_OVERRIDES.get(k)
        if env and os.getenv(env):
            try:
                v = typ(os.getenv(env))
            except ValueError:
                v = d
        out[k] = v
    return out


def coerce(key: str, value: Any) -> Any:
    """Ép kiểu và kiểm tra khoảng giá trị; ném ValueError nếu sai."""
    if key not in SPEC:
        raise ValueError(f"không có cấu hình '{key}'")
    _, typ, lo, hi, _ = SPEC[key]
    try:
        v = typ(float(value)) if typ is int else typ(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' phải là số")
    if not (lo <= v <= hi):
        raise ValueError(f"'{key}' phải nằm trong khoảng {lo} đến {hi}")
    return v


def describe() -> Dict[str, dict]:
    return {k: {"default": d, "min": lo, "max": hi, "type": typ.__name__, "help": h}
            for k, (d, typ, lo, hi, h) in SPEC.items()}


def enroll_cfg(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Cấu hình cho common/enrollselect.py lấy từ settings (khoá enroll_*/aug_*)."""
    g = lambda k: settings[k]
    return {"w_det": g("enroll_w_det"), "w_size": g("enroll_w_size"), "w_blur": g("enroll_w_blur"),
            "w_light": g("enroll_w_light"), "w_pose": g("enroll_w_pose"), "min_det": g("enroll_min_det"),
            "min_w": g("enroll_min_width"), "min_blur": g("enroll_min_blur"), "outlier_cos": g("enroll_outlier_cos"), "target": g("enroll_target"),
            "min_per_dir": g("enroll_min_per_dir"), "min_real": g("enroll_min_real"), "aug_min_cos": g("aug_min_cos"),
            "aug_max_ratio": g("aug_max_ratio"), "aug_cap_total": g("aug_cap_total")}
