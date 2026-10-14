"""Đo thời gian đăng ký: đường cũ (/api/pose rồi /api/enroll/frame) và đường mới (phiên CLB).
Dùng:  python tools/bench_enroll.py --url http://localhost:7860 --token dev --video clip.mp4 [--frames 60] [--width 640]
Chỉ dùng thư viện đã có (requests, opencv). Số liệu in ra là số đo thật trên máy chạy lệnh; không có số nào được hard-code."""
import argparse
import statistics as st
import sys
import time

import cv2
import requests


def frames_from(path, n, width):
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    out, step = [], max(1, total // n)
    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, f = cap.read()
        if not ok:
            continue
        h, w = f.shape[:2]
        if w > width:
            f = cv2.resize(f, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            out.append(buf.tobytes())
        if len(out) >= n:
            break
    return out


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else float("nan")


def line(name, ms, extra=""):
    print(f"{name:34s} n={len(ms):3d}  median {st.median(ms):7.1f} ms   p95 {pct(ms, .95):7.1f} ms  {extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:7860")
    ap.add_argument("--token", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--member", default="bench")
    a = ap.parse_args()
    H = {"X-API-Token": a.token}
    u = a.url.rstrip("/")
    jpgs = frames_from(a.video, a.frames, a.width)
    if not jpgs:
        sys.exit("Không đọc được khung hình nào từ video.")
    print(f"{len(jpgs)} khung, ảnh ~{sum(map(len, jpgs)) // len(jpgs) // 1024} KB/khung, rộng {a.width}px")
    requests.post(f"{u}/api/members", json={"member_id": a.member, "name": "Bench"}, headers=H).raise_for_status()

    t = []
    for j in jpgs:
        t0 = time.perf_counter()
        requests.post(f"{u}/api/pose", files={"file": ("f.jpg", j)}, data={"size": 320}, headers=H).raise_for_status()
        t.append((time.perf_counter() - t0) * 1000)
    line("CŨ  /api/pose (chỉ góc)", t)
    t = []
    for j in jpgs:
        t0 = time.perf_counter()
        requests.post(f"{u}/api/enroll/frame", files={"file": ("f.jpg", j)}, data={"member_id": a.member, "flip": "true"}, headers=H).raise_for_status()
        t.append((time.perf_counter() - t0) * 1000)
    line("CŨ  /api/enroll/frame (lưu 1 khung)", t, "(mỗi khung = 1 request pose + 1 request lưu)")
    requests.delete(f"{u}/api/members/{a.member}/embeddings", headers=H)

    r = requests.post(f"{u}/api/enroll/session", json={"member_id": a.member, "mode": "replace"}, headers=H)
    r.raise_for_status()
    sid = r.json()["sid"]
    t, srv, states = [], [], {}
    for j in jpgs:
        t0 = time.perf_counter()
        r = requests.post(f"{u}/api/enroll/session/{sid}/frames", files={"files": ("f.jpg", j)}, headers=H)
        r.raise_for_status()
        t.append((time.perf_counter() - t0) * 1000)
        srv.append(r.json()["ms"])
        s = r.json()["results"][0]["state"]
        states[s] = states.get(s, 0) + 1
    line("MỚI /session/frames", t, f"(server xử lý median {st.median(srv):.1f} ms; trạng thái {states})")
    t0 = time.perf_counter()
    r = requests.post(f"{u}/api/enroll/session/{sid}/finish", json={"commit": True}, headers=H)
    dt = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    rep = r.json()["report"]
    print(f"MỚI finish+ghi DB: {dt:.0f} ms | giữ {rep['kept']} mẫu, lật {rep['flips']}, aug {rep['aug']}, theo hướng {rep['per_dir']}, kết luận: {rep['verdict']}")
    requests.delete(f"{u}/api/members/{a.member}", headers=H)


if __name__ == "__main__":
    main()
