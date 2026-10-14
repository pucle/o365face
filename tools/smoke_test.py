"""Kiểm tra sau deploy (Hugging Face, Vercel hay local):
    python tools/smoke_test.py https://user-space.hf.space --token API_TOKEN [--hf-token hf_xxx]
    python tools/smoke_test.py https://ten-ban.vercel.app --token API_TOKEN      # qua proxy Vercel
Kiểm: /api/health, từ chối khi thiếu/sai token, nhận token đúng, tạo-xoá thành viên thử, /api/pose, UI, thời gian phản hồi."""
import argparse, sys, time
import requests

ap = argparse.ArgumentParser(); ap.add_argument("url"); ap.add_argument("--token", required=True); ap.add_argument("--hf-token")
a = ap.parse_args(); U = a.url.rstrip("/"); ok = True
H = {"X-API-Token": a.token.strip()}
if a.hf_token: H["Authorization"] = "Bearer " + a.hf_token
BASE = {"Authorization": H["Authorization"]} if a.hf_token else {}


def check(name, cond, info=""):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, info)


def req(m, p, **kw):
    t = time.time(); r = requests.request(m, U + p, timeout=120, **kw); return r, time.time() - t


try:
    r, dt = req("GET", "/api/health", headers=BASE)
    if r.status_code in (401, 403) and not a.hf_token:
        sys.exit("FAIL Space private: cần --hf-token (token Hugging Face).")
    check("health", r.status_code == 200 and r.json().get("ok"), f"{r.status_code} {r.text[:120]} ({dt:.1f}s; nếu Space đang ngủ lần đầu có thể mất vài chục giây)")
    check("không token -> bị từ chối", req("GET", "/api/members", headers=BASE)[0].status_code in (401, 403))
    check("sai token -> bị từ chối", req("GET", "/api/members", headers={**BASE, "X-API-Token": "sai-token"})[0].status_code in (401, 403))
    r, _ = req("GET", "/api/members", headers=H)
    check("token đúng", r.status_code == 200, r.text[:100] if r.status_code != 200 else "")
    if r.status_code == 200:
        r, _ = req("POST", "/api/members", headers=H, json={"member_id": "smoke_test", "name": "Smoke Test"}); check("tạo thành viên thử", r.status_code == 200, r.text[:100])
        import numpy as np, cv2
        img = cv2.imencode(".jpg", np.full((240, 320, 3), 127, np.uint8))[1].tobytes()
        r, dt = req("POST", "/api/pose", headers=H, files={"file": ("x.jpg", img)}); check("/api/pose (ảnh trống -> 0 mặt)", r.status_code == 200 and r.json().get("faces") == [], f"{r.status_code} {dt:.1f}s")
        r, _ = req("DELETE", "/api/members/smoke_test", headers=H); check("xoá thành viên thử", r.status_code == 200)
    r, _ = req("GET", "/ui/index.html" if "hf.space" in U or "localhost" in U or "127.0.0.1" in U else "/", headers=BASE)
    check("UI tải được", r.status_code == 200 and "Điểm danh" in r.text, r.status_code)
except requests.RequestException as e:
    ok = False; print("FAIL không kết nối được:", e)
print("SMOKE OK" if ok else "SMOKE FAILED"); sys.exit(0 if ok else 1)
