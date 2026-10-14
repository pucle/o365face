"""Điểm vào RIÊNG để thu thập khuôn mặt thành viên (giai đoạn 1) — chỉ có: thành viên, đăng ký mặt, nhập dataset, xuất dữ liệu.
Cam cửa, cam trần, ca trực, báo cáo bị khoá (trả 404) và không chạy vòng hiện diện, nên nhẹ và an toàn hơn.
Vector khuôn mặt ghi thẳng vào DATABASE_URL (Neon); sau khi đủ dữ liệu, đổi lệnh chạy sang `server.app:app` (APP_MODE=full)
là dùng tiếp cùng CSDL đó cho điểm danh.

    uvicorn server.enroll_app:app --host 0.0.0.0 --port $PORT
"""
import os

os.environ["APP_MODE"] = "enroll"
os.environ.setdefault("LITE_MODE", "1")

from server.app import app  # noqa: E402,F401
