"""Kiểm thử tích hợp với server đang chạy + model thật.  python tools/integration_real.py IMAGE [URL] [TOKEN]
IMAGE: ảnh có >=2 người khác nhau (ví dụ insightface/data/images/t1.jpg)."""
import sys, io, json
import cv2, numpy as np, requests

img_path = sys.argv[1]
URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:7860"
H = {"X-API-Token": sys.argv[3] if len(sys.argv) > 3 else "dev"}
ok_all = True


def check(name, cond, info=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)


def jpg(a, q=92):
    return cv2.imencode(".jpg", a, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


def post(path, files=None, data=None, **kw):
    return requests.post(URL + path, headers=H, files=files, data=data, timeout=120, **kw)


full = cv2.imread(img_path)
r = post("/api/recognize", files={"file": ("f.jpg", jpg(full))}, data={"context": "door"})
check("recognize full image", r.status_code == 200, r.status_code)
faces = r.json()["faces"]
faces = [f for f in faces if f["width"] >= 60][:2]
check("found >=2 faces", len(faces) >= 2, len(faces))


def crop(f, m=1.2):
    x1, y1, x2, y2 = f["bbox"]; cx, cy = (x1 + x2) / 2, (y1 + y2) / 2; s = max(x2 - x1, y2 - y1) * m * 1.6
    a, b = int(max(0, cx - s / 2)), int(max(0, cy - s / 2))
    return full[b:int(cy + s / 2), a:int(cx + s / 2)]


crops = [crop(f) for f in faces]
check("auth required", requests.post(URL + "/api/members", json={"member_id": "x", "name": "x"}).status_code in (401, 403))
for mid, nm in (("an", "An"), ("binh", "Binh")):
    r = requests.post(URL + "/api/members", headers=H, json={"member_id": mid, "name": nm})
    check("create " + mid, r.status_code == 200, r.text[:100])
r = post("/api/pose", files={"file": ("f.jpg", jpg(crops[0]))})
check("pose", r.status_code == 200 and len(r.json()["faces"]) >= 1, r.text[:160])
for mid, c in (("an", crops[0]), ("binh", crops[1])):
    r = post("/api/enroll/frame", files={"file": ("f.jpg", jpg(c))}, data={"member_id": mid, "source": "door", "step": "C_level"})
    check("enroll frame " + mid, r.status_code == 200 and r.json().get("accepted"), r.text[:200])
    r = post("/api/enroll/batch", files=[("files", ("f%d.jpg" % i, jpg(c, 60 + i * 8))) for i in range(4)],
             data={"member_id": mid, "source": "door"})
    check("enroll batch " + mid, r.status_code == 200, r.text[:200])
# genuine probes: degraded + flipped + downscaled + high-angle-like squash
def variants(c):
    h, w = c.shape[:2]
    return {"flip": cv2.flip(c, 1), "small": cv2.resize(c, (w // 2, h // 2)),
            "blur": cv2.GaussianBlur(c, (0, 0), 2), "dark": (c * 0.5).astype(np.uint8),
            "squash": cv2.resize(c, (w, int(h * 0.8)))}
for mid, c in (("an", crops[0]), ("binh", crops[1])):
    for nm, v in variants(c).items():
        r = post("/api/recognize", files={"file": ("f.jpg", jpg(v))}, data={"context": "room"})
        fs = r.json().get("faces", [])
        got = fs[0]["member_id"] if fs else None
        check(f"room recognize {mid}/{nm}", got == mid, fs[0] if fs else "no face")
r = post("/api/recognize", files={"file": ("f.jpg", jpg(full))}, data={"context": "door"})
print(json.dumps([{k: f[k] for k in ("member_id", "score", "reason")} for f in r.json()["faces"]][:8]))
# --- phiên đăng ký kiểu CLB (dataset): chọn mẫu, bổ sung, giống người khác, undo ---
def session(mid, imgs, **fin):
    r = requests.post(URL + "/api/enroll/session", headers=H, json={"member_id": mid, "kind": "dataset", "mode": fin.pop("mode", "add")}); r.raise_for_status()
    sid = r.json()["sid"]
    for i in range(0, len(imgs), 4):
        post(f"/api/enroll/session/{sid}/frames", files=[("files", (f"f{i + j}.jpg", jpg(v))) for j, v in enumerate(imgs[i:i + 4])]).raise_for_status()
    return requests.post(URL + f"/api/enroll/session/{sid}/finish", headers=H, json={"commit": True, **fin}, timeout=120)


def mutate(c, n):
    out = []
    for i in range(n):
        v = cv2.convertScaleAbs(c, alpha=0.8 + 0.05 * i, beta=-10 + 6 * i)
        h, w = v.shape[:2]; k = 1 + i % 3
        out.append(cv2.resize(v[k:h - k, k:w - k], (w, h)))
    return out
before = requests.get(URL + "/api/members/an", headers=H).json()
r = session("an", mutate(crops[0], 6))
rep = r.json().get("report", {}) if r.status_code == 200 else {}
check("session add: bổ sung vào người đã có", r.status_code == 200 and rep.get("committed", True) is not None and rep.get("kept", 0) >= 1 and rep.get("existing_real", 0) >= 1, r.text[:200])
after = requests.get(URL + "/api/members/an", headers=H).json()
check("session add: số mẫu tăng, không xoá mẫu cũ", after["real"] == before["real"] + rep.get("kept", 0) and after["images"] > before["images"], (before["real"], after["real"], rep.get("kept")))
check("session: bản lật có, không ghi ảnh", rep.get("flips", 0) == rep.get("kept", 0))
check("session: augmentation tự bật khi thiếu mẫu và có trần", rep.get("augmented") is True and rep.get("aug", 0) <= int(0.5 * rep.get("total_real", 1)),
      (rep.get("aug"), rep.get("total_real"), rep.get("augment_reasons")))
check("session: aug không tính vào mẫu gốc", after["aug"] == rep.get("aug", 0) and after["real"] == before["real"] + rep["kept"])
r = session("binh", mutate(crops[0], 6))
rep2 = r.json().get("report", {})
check("session: ảnh của người khác bị chặn (không lưu)", r.json().get("committed") is False and rep2.get("rejected", {}).get("looks_like_other", 0) >= 1, json.dumps(rep2.get("rejected")))
check("session: cảnh báo nêu tên người giống", any("An" in w for w in rep2.get("warnings", [])), rep2.get("warnings"))
r = session("an", mutate(crops[0], 4), augment="off")
check("session augment=off: không sinh bản augmentation", r.json()["report"].get("aug", 0) == 0, r.text[:150])
ids = r.json().get("img_ids", [])
if ids:
    u = requests.post(URL + "/api/enroll/undo", headers=H, json={"member_id": "an", "img_ids": ids})
    check("undo xoá đúng lần lưu vừa rồi", u.status_code == 200 and u.json()["deleted"] >= len(ids), u.text[:120])
check("session hết hạn/không tồn tại -> 404", post("/api/enroll/session/khong_co/frames", files=[("files", ("f.jpg", jpg(crops[0])))]).status_code == 404)
r = post("/api/enroll/dataset", files=[("files", ("f%d.jpg" % i, jpg(v))) for i, v in enumerate(mutate(crops[1], 4))], data={"member_id": "binh", "source": "door"})
check("/api/enroll/dataset (một yêu cầu, tương thích cũ)", r.status_code == 200 and "report" in r.json() and r.json()["kept"] >= 1, r.text[:200])

# check-in burst
r = post("/api/checkin", files=[("files", ("f%d.jpg" % i, jpg(crops[0], 70 + i * 5))) for i in range(4)])
check("checkin rejects extreme pose (yaw -54)", r.json()["status"] == "no_usable_face", r.json()["status"])
r = post("/api/checkin", files=[("files", ("f%d.jpg" % i, jpg(crops[1], 70 + i * 5))) for i in range(4)])
check("checkin", r.status_code == 200 and r.json()["status"] == "checkin" and r.json()["member_id"] == "binh", r.text[:200])
r = post("/api/checkin", files=[("files", ("f%d.jpg" % i, jpg(crops[1]))) for i in range(3)])
check("checkin again -> already", r.json()["status"] != "checkin", r.json()["status"])
# stranger rejected? (binh is enrolled, so use an unrelated synthetic noise image)
noise = np.random.RandomState(1).randint(0, 255, (400, 400, 3), np.uint8)
r = post("/api/checkin", files=[("files", ("n.jpg", jpg(noise)))])
check("noise -> no face", r.json()["status"] == "no_usable_face", r.json()["status"])
# room
r = post("/api/room/frame", files={"file": ("f.jpg", jpg(full))})
check("room frame", r.status_code == 200, r.text[:300])
r = post("/api/room/identify", data={"track_ids": "1,2"}, files=[("files", ("a.jpg", jpg(crops[0]))), ("files", ("b.jpg", jpg(crops[1])))])
check("room identify", r.status_code == 200, r.text[:300])
r = requests.post(URL + "/api/room/update", headers=H, json={"persons": 2, "identified": [{"member_id": "binh", "score": 0.7, "source": "face"}], "strangers": 0})
check("room update", r.status_code == 200, r.text[:300])
st = requests.get(URL + "/api/status", headers=H).json()
check("status", r.status_code == 200, json.dumps(st)[:300])
c = requests.get(URL + "/api/calibration", headers=H)
check("calibration", c.status_code == 200, json.dumps(c.json())[:300])
s = requests.post(URL + "/api/settings", headers=H, json={"door_threshold": 0.5})
check("settings set", s.status_code == 200, s.text[:200])
s = requests.post(URL + "/api/settings", headers=H, json={"door_threshold": 9})
check("settings invalid rejected", s.status_code in (400, 422), s.status_code)
requests.post(URL + "/api/settings", headers=H, json={"door_threshold": 0.45})
r = requests.get(URL + "/api/report", headers=H); check("report", r.status_code == 200, r.text[:200])
r = requests.get(URL + "/api/report.csv", headers=H); check("report csv", r.status_code == 200)
r = requests.get(URL + "/api/backup", headers=H); check("backup", r.status_code == 200 and r.content[:6] == b"SQLite")
print("ALL OK" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
