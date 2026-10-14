"""Cam cửa. Chỉ gọi nhận diện khi 'có người đến check-in' (cùng điều kiện với trang Thử check-in):
đúng một mặt rộng >= --min-width px (khung 480 px), nhìn khá thẳng, ổn định >= --stable giây.
Khi đó gửi một burst 4 khung tới /api/checkin; server bỏ phiếu rồi check-in.

    python client/door_client.py --url https://<space>.hf.space --token XXX --source 0 --show
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402

from client import net  # noqa: E402

COOL = {"checkin": 20, "already": 15, "unknown": 4, "no_usable_face": 2}


def main():
    ap = argparse.ArgumentParser()
    net.add_common(ap)
    ap.add_argument("--min-width", type=int, default=90)
    ap.add_argument("--stable", type=float, default=0.7)
    ap.add_argument("--poll", type=float, default=0.4, help="giây giữa hai lần hỏi vị trí mặt")
    ap.add_argument("--burst", type=int, default=4)
    a = ap.parse_args()
    srv = net.from_env(a)
    a.source = net.resolve_source(srv, "door", a.source)
    cap = net.open_capture(a.source)
    since, until, last_poll, msg = None, 0.0, 0.0, ""
    print("Cam cửa chạy. Ctrl+C để dừng.")
    while True:
        ok, frame = cap.read()
        if not ok:
            if str(a.source).isdigit():
                time.sleep(0.5); continue
            break                                               # hết video
        now = time.time()
        if a.show:
            cv2.putText(frame, msg, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            cv2.imshow("door", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        if not a.always and not net.is_open(a.open, a.close):
            time.sleep(5); continue
        if now < until or now - last_poll < a.poll:
            if not a.show:
                time.sleep(0.03)
            continue
        last_poll = now
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (480, int(h * 480 / w)))
        try:
            faces = srv.post("/api/pose", files={"file": ("f.jpg", net.jpeg(small, 70))}, data={"size": 320})["faces"]
        except Exception as e:
            print("pose lỗi:", e); time.sleep(2); continue
        f = faces[0] if len(faces) == 1 else None
        good = f and f["width"] >= a.min_width and abs(f.get("yaw") or 0) <= 35 and abs(f.get("pitch") or 0) <= 25
        if not good:
            since = None; continue
        since = since or now
        if now - since < a.stable:
            continue
        since = None
        shots = []
        for _ in range(a.burst):
            ok, fr = cap.read()
            if ok:
                shots.append(("files", ("f.jpg", net.jpeg(cv2.resize(fr, (640, int(fr.shape[0] * 640 / fr.shape[1]))), 90))))
            time.sleep(0.15)
        try:
            r = srv.post("/api/checkin", files=shots)
        except Exception as e:
            print("check-in lỗi:", e); time.sleep(2); continue
        st = r.get("status")
        msg = f"{st} {r.get('name', '')}"
        print(time.strftime("%H:%M:%S"), st, r.get("name", ""), r.get("score", ""), "(đang trong ca)" if r.get("on_shift") else "")
        until = time.time() + COOL.get(st, 5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
