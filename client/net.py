"""Dùng chung cho các client: gọi server, giờ hoạt động."""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Ho_Chi_Minh"))
except Exception:
    TZ = timezone(timedelta(hours=7))


class Server:
    def __init__(self, url, token, hf_token=None, timeout=30):
        self.url = url.rstrip("/")
        self.h = {"X-API-Token": token}
        if hf_token:                       # Space private: Hugging Face dùng header Authorization
            self.h["Authorization"] = "Bearer " + hf_token
        self.timeout = timeout
        self.s = requests.Session()

    def post(self, path, **kw):
        r = self.s.post(self.url + path, headers=self.h, timeout=self.timeout, **kw)
        r.raise_for_status()
        return r.json()

    def delete(self, path, **kw):
        r = self.s.delete(self.url + path, headers=self.h, timeout=self.timeout, **kw)
        r.raise_for_status()
        return r.json()

    def get(self, path, **kw):
        r = self.s.get(self.url + path, headers=self.h, timeout=self.timeout, **kw)
        r.raise_for_status()
        return r.json()


def from_env(args):
    token = args.token or os.getenv("API_TOKEN", "")
    if not token:
        sys.exit("Thiếu API token: dùng --token hoặc biến môi trường API_TOKEN.")
    return Server(args.url or os.getenv("SERVER_URL", "http://127.0.0.1:7860"), token, os.getenv("HF_TOKEN"))


def is_open(open_h, close_h):
    h = datetime.now(TZ).hour
    return open_h <= h < close_h


def add_common(ap):
    ap.add_argument("--url", help="địa chỉ server (hoặc SERVER_URL)")
    ap.add_argument("--token", help="API token (hoặc API_TOKEN)")
    ap.add_argument("--source", default="auto", help="auto = lấy từ trang Camera trên web (mặc định; không có thì dùng webcam 0); hoặc số webcam (0,1..), đường dẫn video, rtsp://")
    ap.add_argument("--open", type=int, default=8)
    ap.add_argument("--close", type=int, default=20)
    ap.add_argument("--always", action="store_true", help="bỏ qua giờ mở/đóng (để thử)")
    ap.add_argument("--show", action="store_true", help="hiện cửa sổ xem trước (cần opencv-python, không headless)")


def resolve_source(srv, role, source):
    """--source auto: hỏi server camera đã chọn cho vai trò 'door'/'room' (trang Camera). Lỗi mạng hoặc chưa cấu hình -> webcam 0."""
    if str(source).lower() != "auto":
        return source
    try:
        src = (srv.get("/api/cameras").get(role) or {}).get("source", "").strip()
    except Exception as e:
        print(f"[camera] không lấy được cấu hình từ server ({e}); dùng webcam 0")
        src = ""
    src = src or "0"
    print(f"[camera] {role}: nguồn = {src if not src.lower().startswith('rtsp') else 'rtsp://***'}")
    return src


def open_capture(src):
    import cv2
    cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
    if not cap.isOpened():
        sys.exit(f"Không mở được camera/nguồn: {src}")
    return cap


def jpeg(img, q=88):
    import cv2
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()
