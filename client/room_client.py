"""Cam trong phòng (cam trần).

--mode yolo  (khuyến nghị): YOLO + ByteTrack theo dõi từng người; chỉ cắt ảnh người CHƯA biết danh tính gửi lên
             /api/room/identify; người vừa check-in ở cửa được gán tự động cho track mới xuất hiện ở vùng cửa
             (--door-zone). Báo số người + danh sách lên /api/room/update mỗi --beat giây.
--mode frame (đơn giản, không cần ultralytics): gửi cả khung hình mỗi --every giây tới /api/room/frame.

    pip install ultralytics
    python client/room_client.py --url https://<space>.hf.space --token XXX --source rtsp://... --door-zone 0,0.5,0.3,1
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2  # noqa: E402

from client import net  # noqa: E402
from common.roompipe import RoomPipeline  # noqa: E402


def run_frame(a, srv, cap):
    last = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            if str(a.source).isdigit(): time.sleep(0.5); continue
            break
        now = time.time()
        if a.show:
            cv2.imshow("room", fr)
            if cv2.waitKey(1) & 0xFF == ord("q"): break
        if now - last < a.every: continue
        if not a.always and not net.is_open(a.open, a.close): time.sleep(5); continue
        last = now
        h, w = fr.shape[:2]
        s = min(1.0, 1600 / max(h, w))
        try:
            r = srv.post("/api/room/frame", files={"file": ("f.jpg", net.jpeg(cv2.resize(fr, None, fx=s, fy=s), 90))})
            print(time.strftime("%H:%M:%S"), "thấy", len(r["faces"]), "mặt; nhận ra:", [f["name"] for f in r["faces"] if f.get("member_id")])
        except Exception as e:
            print("lỗi:", e); time.sleep(2)


def run_yolo(a, srv, cap):
    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("Chế độ yolo cần: pip install ultralytics  (hoặc dùng --mode frame)")
    model = YOLO(a.model)
    zone = tuple(float(x) for x in a.door_zone.split(","))
    frame_ref = {"img": None}

    def identify(items):
        img = frame_ref["img"]
        h, w = img.shape[:2]
        files, ids = [], []
        for tid, (x1, y1, x2, y2) in items:
            bw, bh = x2 - x1, y2 - y1                          # mở rộng nhẹ, lấy phần đầu-vai (nửa trên người)
            xa, xb = int(max(0, x1 - 0.1 * bw)), int(min(w, x2 + 0.1 * bw))
            ya, yb = int(max(0, y1 - 0.05 * bh)), int(min(h, y1 + 0.6 * bh))
            crop = img[ya:yb, xa:xb]
            if crop.size == 0: continue
            files.append(("files", ("c.jpg", net.jpeg(crop, 92)))); ids.append(str(tid))
        if not files: return {}
        res = srv.post("/api/room/identify", data={"track_ids": ",".join(ids)}, files=files)["results"]
        return {r["track_id"]: r for r in res}

    pipe = RoomPipeline(identify, door_zone=zone, min_box_h=a.min_box_h)
    pending, last_beat, n_frame = [], 0, 0
    for r in model.track(source=int(a.source) if str(a.source).isdigit() else a.source, stream=True, persist=True,
                         classes=[0], conf=a.conf, tracker="bytetrack.yaml", verbose=False, imgsz=a.imgsz):
        n_frame += 1
        if n_frame % a.skip: continue
        if not a.always and not net.is_open(a.open, a.close): time.sleep(2); continue
        img = r.orig_img; frame_ref["img"] = img
        h, w = img.shape[:2]
        tracks = []
        if r.boxes is not None and r.boxes.id is not None:
            for tid, b in zip(r.boxes.id.int().tolist(), r.boxes.xyxy.tolist()):
                tracks.append((tid, tuple(b)))
        try:
            out = pipe.step(time.time(), tracks, (w, h), pending)
        except Exception as e:
            print("nhận diện lỗi:", e); time.sleep(1); continue
        if a.show:
            for t in out["identified"]:
                pass
            vis = img.copy()
            names = {i["track_id"]: i["member_id"] for i in out["identified"]}
            for tid, (x1, y1, x2, y2) in tracks:
                cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), (0, 200, 0) if tid in names else (0, 0, 255), 2)
                cv2.putText(vis, names.get(tid, "?"), (int(x1), int(y1) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("room", vis)
            if cv2.waitKey(1) & 0xFF == ord("q"): break
        now = time.time()
        if now - last_beat >= a.beat or out["bound"]:
            last_beat = now
            try:
                u = srv.post("/api/room/update", json={"persons": out["persons"], "strangers": out["strangers"],
                                                       "identified": [{"member_id": i["member_id"], "score": i["score"], "source": i["source"]} for i in out["identified"]],
                                                       "bound": out["bound"]})
                pending = u.get("pending", [])
                print(time.strftime("%H:%M:%S"), f"{out['persons']} người, nhận ra {[i['member_id'] for i in out['identified']]}, lạ {out['strangers']}")
            except Exception as e:
                print("update lỗi:", e)


def main():
    ap = argparse.ArgumentParser()
    net.add_common(ap)
    ap.add_argument("--mode", choices=["yolo", "frame"], default="yolo")
    ap.add_argument("--every", type=float, default=2.0, help="(frame) giây giữa hai khung gửi")
    ap.add_argument("--model", default="yolov8n.pt")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--skip", type=int, default=3, help="chỉ xử lý 1/N khung hình")
    ap.add_argument("--beat", type=float, default=5.0, help="giây giữa hai lần báo /api/room/update")
    ap.add_argument("--min-box-h", type=int, default=70)
    ap.add_argument("--door-zone", default="0,0.5,0.3,1", help="x1,y1,x2,y2 (tỉ lệ 0..1) vùng gần cửa trong khung cam trần")
    a = ap.parse_args()
    srv = net.from_env(a)
    a.source = net.resolve_source(srv, "room", a.source)
    print("Cam phòng chạy. Ctrl+C để dừng.")
    if a.mode == "frame":
        run_frame(a, srv, net.open_capture(a.source))
    else:
        run_yolo(a, srv, None)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
