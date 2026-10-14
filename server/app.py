"""Server chấm công khuôn mặt cho CLB.  Chạy:  uvicorn server.app:app --port 7860

Giao diện web: http://localhost:7860/ui/
Biến môi trường:
  API_TOKEN       (bắt buộc) mật khẩu API/giao diện; để trống thì mọi yêu cầu bị từ chối
  DATA_DIR        thư mục lưu DB (mặc định ./data; trên Hugging Face dùng /data nếu có persistent storage)
  MODEL_NAME      buffalo_l (mặc định, chính xác hơn) hoặc buffalo_s (nhanh hơn)
  TZ_NAME         múi giờ, mặc định Asia/Ho_Chi_Minh
  INSIGHTFACE_HOME  nơi lưu model (mặc định ~/.insightface)
Ngưỡng và thời gian chỉnh trong giao diện (trang Hiệu chỉnh), xem common/config.py.
"""
from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import logging
import os
import sys
import tempfile
import threading
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import calibration, config, posebins  # noqa: E402
from common.matching import Gallery  # noqa: E402
from common.presence import AWAY, PRESENT, Absence, PresenceEngine, Shift  # noqa: E402
from server import enrolling  # noqa: E402
from server.face_engine import Face, FaceEngine, decode_image  # noqa: E402
from server.memguard import MemGuard, rss_mb, trim  # noqa: E402
from server.storage import Storage  # noqa: E402

log = logging.getLogger("club")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

try:
    TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Ho_Chi_Minh"))
except Exception:                      # Windows thiếu gói tzdata -> dùng cố định UTC+7
    TZ = timezone(timedelta(hours=7))

# Windows `set API_TOKEN=abc ` giữ lại khoảng trắng/dấu nháy ở cuối -> bỏ đi để khỏi lệch
API_TOKEN = os.getenv("API_TOKEN", "").strip().strip("\"'").strip()
DATA_DIR = os.getenv("DATA_DIR", "/data" if os.path.isdir("/data") else "./data")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ID_RE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")

# Cổng chất lượng khi đăng ký: nguồn "door" yêu cầu mặt rõ, "room" chấp nhận mặt nhỏ/nhìn từ trên cao
ENROLL_GATES = {
    "door": dict(min_det=0.60, min_w=80, max_yaw=60.0, max_pitch=50.0, min_blur=35.0),
    "room": dict(min_det=0.45, min_w=40, max_yaw=85.0, max_pitch=75.0, min_blur=15.0),
}
MAX_IMAGES_PER_MEMBER = 150
# APP_MODE=enroll: chỉ thu thập khuôn mặt thành viên (server/enroll_app.py); APP_MODE=full: đủ chức năng
APP_MODE = os.getenv("APP_MODE", "full").strip().lower()
LITE = os.getenv("LITE_MODE", "0") == "1"
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "8"))
ENROLL_ONLY_PREFIXES = ("/health", "/api/health", "/api/members", "/api/enroll", "/api/pose", "/api/export", "/api/events",
                        "/api/status", "/api/settings", "/ui", "/docs", "/openapi.json")
EVENT_KEEP_DAYS = int(os.getenv("EVENT_KEEP_DAYS", "180"))
HANDOFF_TTL_S = 60
DOOR_MIN_W, DOOR_MAX_YAW, DOOR_MAX_PITCH = 80, 40.0, 30.0


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)          # giờ địa phương, không kèm tzinfo


def to_local_naive(dt: datetime) -> datetime:
    return dt.astimezone(TZ).replace(tzinfo=None) if dt.tzinfo else dt


class Ctx:
    engine: FaceEngine
    store: Storage
    gallery: Gallery
    presence: PresenceEngine
    settings: Dict[str, Any]
    glock = threading.RLock()                 # bảo vệ gallery khi thêm/xoá mẫu
    plock = threading.RLock()                 # bảo vệ presence engine
    handoff: Dict[str, datetime] = {}         # member_id -> lúc check-in ở cửa, chờ cam trần gán track
    room: Dict[str, Any] = {"persons": 0, "strangers": 0, "ts": None, "identified": []}
    frame_votes: Dict[str, List[datetime]] = {}
    started: Optional[datetime] = None
    guard: Optional[MemGuard] = None
    last_prune: Optional[datetime] = None
    last_snap: str = ""
    last_snap_ts: Optional[datetime] = None
    last_alert: Dict[str, datetime] = {}
    sessions = enrolling.SessionStore()      # phiên đăng ký kiểu CLB (RAM, có TTL)


ctx = Ctx()


# --------------------------------------------------------------------- tiện ích
def auth(x_api_token: str = Header(default="")) -> None:
    # Header riêng X-API-Token để header Authorization còn trống cho token Hugging Face (Space Private).
    # Fail-closed: chưa đặt API_TOKEN thì từ chối tất cả.
    if not API_TOKEN:
        raise HTTPException(401, "Server chưa đặt biến môi trường API_TOKEN (đặt rồi chạy lại uvicorn).")
    if not x_api_token.strip():
        raise HTTPException(401, "Trình duyệt chưa gửi token: bấm nút Token và nhập API_TOKEN.")
    if not hmac.compare_digest(x_api_token.strip().encode("utf-8"), API_TOKEN.encode("utf-8")):
        raise HTTPException(401, "Token không khớp API_TOKEN của server (kiểm tra khoảng trắng/dấu nháy).")


def S(key: str):
    return ctx.settings[key]


def read_image(up: UploadFile) -> Optional[np.ndarray]:
    try:
        return decode_image(up.file.read())
    except Exception:
        return None


def check_member_id(member_id: str) -> str:
    member_id = (member_id or "").strip()
    if not member_id or len(member_id) > 40 or not member_id.strip(".") or any(c not in ID_RE_CHARS for c in member_id):
        raise HTTPException(400, "Mã thành viên chỉ gồm chữ không dấu, số, '-', '_' hoặc '.', tối đa 40 ký tự.")
    return member_id


def load_gallery() -> None:
    rows = ctx.store.all_embeddings()
    with ctx.glock:
        ctx.gallery.load([(r["member_id"], r["vec"], {"source": r["source"], "pitch": r["pitch"], "yaw": r["yaw"],
                                                       "img": r["img"], "step": r["step"]}) for r in rows])


def apply_settings() -> None:
    if hasattr(ctx, "presence"):
        ctx.presence.grace_s = int(S("grace_s"))
        ctx.presence.min_absence_s = int(S("min_absence_s"))


def thresholds(context: str, face: Face):
    high = False
    if face.pitch is not None and face.yaw is not None:
        high = posebins.is_high_angle(face.pitch, face.yaw, S("high_angle_pitch"), S("high_angle_yaw"))
    if context == "door":
        return S("door_threshold"), S("door_margin"), high
    return (S("room_threshold_high") if high else S("room_threshold")), S("room_margin"), high


def recognize_face(face: Face, context: str) -> dict:
    thr, margin, high = thresholds(context, face)
    with ctx.glock:
        d = ctx.gallery.decide(face.emb, thr, margin) if face.emb is not None else \
            {"member_id": None, "best_id": None, "score": -1.0, "margin": 0.0, "reason": "no_embedding"}
    d.update(threshold=thr, margin_required=margin, high_angle=high,
             name=ctx.store.member_name(d["member_id"]), best_name=ctx.store.member_name(d["best_id"]))
    return d


def _summarize(member_id: str, items: list) -> dict:
    """items: [(meta, index)] của một thành viên. Độ phủ/tiến độ chỉ tính mẫu "thật" (không tính bản che/augmentation)."""
    imgs = {md.get("img") for md, _ in items}
    by_source: Dict[str, int] = defaultdict(int)
    real, flips, aug, occ = [], 0, 0, 0
    for md, _ in items:
        by_source[md.get("source") or "?"] += 1
        st = md.get("step") or ""
        if "+" not in st:
            real.append(md)
        elif "+flip" in st:
            flips += 1
        elif "+aug-" in st:
            aug += 1
        elif "+occ-" in st:
            occ += 1
    cov_all = posebins.coverage([(md.get("pitch"), md.get("yaw")) for md, _ in items if "+aug-" not in (md.get("step") or "")
                                 and "+occ-" not in (md.get("step") or "")])
    pts = [(md["pitch"], md["yaw"]) for md in real if md.get("pitch") is not None and md.get("yaw") is not None]
    club = posebins.club_counts(pts)
    target = int(S("enroll_target"))
    min_dir = int(S("enroll_min_per_dir"))
    out = {"member_id": member_id, "name": ctx.store.member_name(member_id), "images": len(imgs),
           "embeddings": len(items), "by_source": dict(by_source), "grid": cov_all["grid"], "profiles": {},
           "poses": [[round(p, 1), round(y, 1)] for p, y in pts],
           "real": len(real), "flips": flips, "aug": aug, "occ": occ, "club": club, "target": target,
           "progress": round(min(1.0, len(real) / target), 3) if target else 1.0,
           "club_missing": posebins.club_missing(club, min_dir),
           "complete": len(real) >= int(S("enroll_min_real")) and not posebins.club_missing(club, min_dir)}
    for prof in posebins.PROFILES:
        miss = posebins.missing(cov_all, prof)
        out["profiles"][prof] = {"score": round(posebins.score(cov_all, prof), 2),
                                 "missing": [{"pitch": p, "yaw": y, "label": posebins.cell_label(p, y)} for p, y in miss]}
    return out


def member_summary(member_id: str) -> dict:
    with ctx.glock:
        items = [(md, i) for i, (m, md) in enumerate(zip(ctx.gallery.ids, ctx.gallery.meta)) if m == member_id]
    return _summarize(member_id, items)


def all_summaries() -> List[dict]:
    """Tóm tắt mọi thành viên chỉ với MỘT lượt duyệt thư viện (không phải mỗi người một lượt)."""
    groups: Dict[str, list] = defaultdict(list)
    with ctx.glock:
        for i, (m, md) in enumerate(zip(ctx.gallery.ids, ctx.gallery.meta)):
            groups[m].append((md, i))
    return [_summarize(mid, groups.get(mid, [])) for mid, _ in ctx.store.members()]


def enroll_face(member_id: str, face: Optional[Face], source: str, step: str, flip: bool,
                dedup: float, img_id: str) -> dict:
    """Lưu một mặt (và bản lật) nếu đạt chất lượng. Trả về {accepted, reason, ...}."""
    if face is None:
        return {"accepted": False, "reason": "no_face"}
    gate = ENROLL_GATES[source]
    info = face.brief()
    if face.emb is None:
        return {"accepted": False, "reason": "no_embedding", **info}
    if face.det_score < gate["min_det"] or face.width < gate["min_w"]:
        return {"accepted": False, "reason": "small_or_unsure", **info}
    if face.blur < gate["min_blur"]:
        return {"accepted": False, "reason": "blurry", **info}
    if face.yaw is not None and (abs(face.yaw) > gate["max_yaw"] or abs(face.pitch) > gate["max_pitch"]):
        return {"accepted": False, "reason": "extreme_pose", **info}
    with ctx.glock:
        if len({md.get("img") for m, md in zip(ctx.gallery.ids, ctx.gallery.meta) if m == member_id}) >= MAX_IMAGES_PER_MEMBER:
            return {"accepted": False, "reason": "limit", **info}
        if ctx.gallery.max_sim(member_id, face.emb) > dedup:
            return {"accepted": False, "reason": "duplicate", **info}
    ts = now().isoformat()
    ctx.store.add_embedding(member_id, face.emb, source, face.pitch, face.yaw, ts, img_id, step)
    meta = {"source": source, "pitch": face.pitch, "yaw": face.yaw, "img": img_id, "step": step}
    with ctx.glock:
        ctx.gallery.add(member_id, face.emb, meta)
    for kind, ev in (face.occ or {}).items():           # bản mô phỏng bị che một phần
        ctx.store.add_embedding(member_id, ev, source, face.pitch, face.yaw, ts, img_id, step + "+occ-" + kind)
        with ctx.glock:
            ctx.gallery.add(member_id, ev, {**meta, "step": step + "+occ-" + kind})
    if flip and face.emb_flip is not None:
        fy = None if face.yaw is None else -face.yaw
        ctx.store.add_embedding(member_id, face.emb_flip, source, face.pitch, fy, ts, img_id, step + "+flip")
        with ctx.glock:
            ctx.gallery.add(member_id, face.emb_flip, {**meta, "yaw": fy, "step": step + "+flip"})
    return {"accepted": True, "reason": "ok", **info}


def day_bounds(day: Optional[date]):
    day = day or now().date()
    lo = datetime.combine(day, datetime.min.time())
    return day, lo.isoformat(), (lo + timedelta(days=1)).isoformat()


def shift_state(member_id: str, start: datetime, end: datetime, ts: datetime) -> str:
    if ts < start:
        return "upcoming"
    if ts >= end:
        return "done"
    return "active"


def check_model_guard() -> None:
    """Vector của model này không so sánh được với vector của model khác: chặn chạy lẫn để khỏi nhận diện sai lặng lẽ."""
    want = ctx.engine.model_name
    saved = ctx.store.kv_get("embedding_model")
    if saved is None:
        saved = "buffalo_l" if ctx.store.query("SELECT 1 FROM embeddings LIMIT 1") else None   # dữ liệu cũ trước khi có ghi chú
    if saved is None:
        ctx.store.kv_set("embedding_model", want)
    elif saved != want and os.getenv("ALLOW_MODEL_MISMATCH") != "1":
        raise RuntimeError(f"CSDL đang chứa vector của model '{saved}' nhưng server chạy '{want}'. "
                           "Đăng ký lại bằng đúng một model (hoặc dùng CSDL/schema mới). Bỏ qua kiểm tra: ALLOW_MODEL_MISMATCH=1 (không khuyến nghị).")
    elif ctx.store.kv_get("embedding_model") is None:
        ctx.store.kv_set("embedding_model", saved)


# --------------------------------------------------------------------- vòng đời
@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx.started = now()
    ctx.store = Storage(DATA_DIR)
    ctx.settings = config.defaults()
    for k, v in (ctx.store.kv_get("settings", {}) or {}).items():
        try:
            ctx.settings[k] = config.coerce(k, v)
        except ValueError:
            pass
    ctx.engine = FaceEngine(os.getenv("MODEL_NAME", "buffalo_l"))
    check_model_guard()
    try:
        log.info("Làm nóng model: %.2f giây", await asyncio.to_thread(ctx.engine.warmup, int(S("det_size_enroll"))))
    except Exception:
        log.exception("làm nóng model lỗi (bỏ qua)")
    ctx.gallery = Gallery()
    load_gallery()

    def on_absence(a: Absence) -> None:
        ctx.store.add_absence(a.member_id, a.start.isoformat(), a.end.isoformat(), a.minutes)

    def on_event(ts: datetime, kind: str, member_id: str) -> None:
        try:
            ctx.store.add_event(ts.isoformat(), kind, member_id)
        except Exception:
            log.exception("không ghi được sự kiện %s (bỏ qua, tiếp tục chạy)", kind)

    ctx.presence = PresenceEngine(grace_s=int(S("grace_s")), min_absence_s=int(S("min_absence_s")),
                                  on_absence=on_absence, on_event=on_event)
    for _id, mid, s, e in ctx.store.all_shifts():
        ctx.presence.add_shift(Shift(mid, datetime.fromisoformat(s), datetime.fromisoformat(e)))
    restored = ctx.presence.restore(ctx.store.kv_get("presence", {}), now())
    log.info("Sẵn sàng: %d mẫu khuôn mặt, %d trạng thái hiện diện được khôi phục, providers=%s",
             len(ctx.gallery.ids), restored, ctx.engine.providers)

    guard = MemGuard(on_hard=lambda: log.warning("bỏ %d phiên đăng ký đang treo", ctx.sessions.clear()))
    ctx.guard = guard

    def maintenance():
        """Mỗi 15 giây: giữ RAM; mỗi ngày một lần: xoá lịch sử quá hạn."""
        guard.check()
        t = now()
        if ctx.last_prune is None or (t - ctx.last_prune).total_seconds() > 86400:
            ctx.last_prune = t
            try:
                n = ctx.store.prune_events((t - timedelta(days=EVENT_KEEP_DAYS)).isoformat())
                if n:
                    log.info("đã xoá %d sự kiện cũ hơn %d ngày", n, EVENT_KEEP_DAYS)
            except Exception:
                log.exception("xoá sự kiện cũ lỗi (bỏ qua)")

    def save_presence(snap):
        # chỉ ghi khi có thay đổi: giữ DB đám mây (Neon) được ngủ, đỡ tốn compute-hours
        # last_seen đổi liên tục nên bỏ khỏi so sánh; vẫn ghi lại tối đa mỗi 5 phút (đủ cho khôi phục sau khi khởi động lại)
        key = json.dumps({m: {k: v for k, v in d.items() if k != "last_seen"} for m, d in snap.items()}, sort_keys=True)
        t = now()
        if key != ctx.last_snap or ctx.last_snap_ts is None or (t - ctx.last_snap_ts).total_seconds() >= 300:
            ctx.store.kv_set("presence", snap)
            ctx.last_snap, ctx.last_snap_ts = key, t

    def tick_once():
        ts = now()
        maintenance()
        if APP_MODE == "enroll":
            return
        with ctx.plock:
            ctx.presence.tick(ts)
            snap = ctx.presence.snapshot()
        save_presence(snap)
        for m, t0 in list(ctx.handoff.items()):
            if (ts - t0).total_seconds() > HANDOFF_TTL_S:
                ctx.handoff.pop(m, None)

    async def ticker():
        while True:
            await asyncio.sleep(15)
            try:
                await asyncio.to_thread(tick_once)
            except Exception:
                log.exception("ticker lỗi")

    task = asyncio.create_task(ticker())
    yield
    task.cancel()
    with ctx.plock:
        snap = ctx.presence.snapshot()
    save_presence(snap)


app = FastAPI(title="Club attendance", lifespan=lifespan)

# UI đặt ở nơi khác (vd Vercel) gọi API qua trình duyệt cần CORS. Đặt CORS_ORIGINS="https://ten-ban.vercel.app" (nhiều giá trị: phẩy).
# Xác thực bằng header X-API-Token (không dùng cookie) nên cho phép "*" cũng không lộ phiên đăng nhập; vẫn nên liệt kê cụ thể.
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"], max_age=600)


@app.middleware("http")
async def guard_requests(request, call_next):
    """Giới hạn kích thước tải lên (tránh ảnh khổng lồ làm tràn RAM) và khoá chức năng ngoài phạm vi khi APP_MODE=enroll."""
    path = request.url.path
    if APP_MODE == "enroll" and path != "/" and not path.startswith(ENROLL_ONLY_PREFIXES):
        return Response(json.dumps({"detail": "Máy chủ đang ở chế độ chỉ thu thập khuôn mặt (APP_MODE=enroll)."}), 404, media_type="application/json")
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_UPLOAD_MB * 1024 * 1024:
        return Response(json.dumps({"detail": f"Yêu cầu quá lớn (> {MAX_UPLOAD_MB:g} MB). Gửi ít ảnh hơn mỗi lần."}), 413, media_type="application/json")
    return await call_next(request)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/health")
@app.get("/api/health")
def health():
    return {"ok": True, "providers": ctx.engine.providers, "model": ctx.engine.model_name,
            "db": ctx.store.kind, "mode": APP_MODE, "lite": LITE, "rss_mb": None if rss_mb() is None else round(rss_mb()),
            "embeddings": len(ctx.gallery.ids), "members": len(ctx.gallery.members())}


ALERT_KINDS = ("alert_unknown_door", "alert_stranger_room")
WARN_KINDS = ("away", "left", "seen_without_checkin")


def raise_alert(kind: str, detail: str, min_gap_s: int = 60) -> None:
    """Ghi cảnh báo vào lịch sử, giới hạn tần suất để không làm đầy DB khi người lạ đứng lâu."""
    ts = now()
    last = ctx.last_alert.get(kind)
    if last and (ts - last).total_seconds() < min_gap_s:
        return
    ctx.last_alert[kind] = ts
    try:
        ctx.store.add_event(ts.isoformat(), kind, None, detail)
    except Exception:
        log.exception("không ghi được cảnh báo %s", kind)


@app.get("/api/events", dependencies=[Depends(auth)])
def api_events(category: str = "all", limit: int = 100, day: Optional[date] = None, member_id: Optional[str] = None):
    """Lịch sử: category = all | alert (người lạ + vắng mặt/rời đi) | checkin."""
    limit = max(1, min(int(limit), 500))
    kinds = None
    if category == "alert":
        kinds = list(ALERT_KINDS + WARN_KINDS)
    elif category == "checkin":
        kinds = ["checkin", "return", "checkout"]
    elif category != "all":
        raise HTTPException(400, "category phải là all, alert hoặc checkin.")
    lo = hi = None
    if day:
        _d, lo, hi = day_bounds(day)
    names = dict(ctx.store.members())
    rows = ctx.store.events_filtered(kinds, limit, lo, hi, member_id)
    return {"events": [{"ts": t, "kind": k, "member_id": m, "name": names.get(m, m or ""), "detail": d,
                        "alert": k in ALERT_KINDS or k in WARN_KINDS} for t, k, m, d in rows]}


# --------------------------------------------------------------------- camera (cấu hình lưu ở máy chủ)
class CamIn(BaseModel):
    source: str = ""          # "", số (USB), hoặc URL rtsp/http
    label: str = ""


class CamsIn(BaseModel):
    door: Optional[CamIn] = None
    room: Optional[CamIn] = None


def _cam_ok(src: str) -> bool:
    src = src.strip()
    return src == "" or src.isdigit() or src.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))


@app.get("/api/cameras", dependencies=[Depends(auth)])
def api_cameras_get():
    cams = ctx.store.kv_get("cameras", {}) or {}
    return {"door": cams.get("door") or {"source": "", "label": ""}, "room": cams.get("room") or {"source": "", "label": ""}}


@app.post("/api/cameras", dependencies=[Depends(auth)])
def api_cameras_set(c: CamsIn):
    cams = ctx.store.kv_get("cameras", {}) or {}
    for role in ("door", "room"):
        v = getattr(c, role)
        if v is None:
            continue
        if not _cam_ok(v.source):
            raise HTTPException(400, "Nguồn camera phải là số (USB), rtsp://… hoặc http(s)://…")
        cams[role] = {"source": v.source.strip(), "label": v.label.strip()[:60]}
    ctx.store.kv_set("cameras", cams)
    return {"ok": True, **cams}


# --------------------------------------------------------------------- thành viên
class MemberIn(BaseModel):
    member_id: str
    name: str


@app.post("/api/members", dependencies=[Depends(auth)])
def api_upsert_member(m: MemberIn):
    mid = check_member_id(m.member_id)
    if not m.name.strip():
        raise HTTPException(400, "Tên không được để trống.")
    ctx.store.upsert_member(mid, m.name.strip(), now().isoformat())
    return {"ok": True, "member_id": mid}


@app.post("/members", dependencies=[Depends(auth)], include_in_schema=False)
def legacy_upsert_member(member_id: str = Form(...), name: str = Form(...)):
    return api_upsert_member(MemberIn(member_id=member_id, name=name))


@app.get("/api/members", dependencies=[Depends(auth)])
def api_members():
    return {"members": all_summaries()}


@app.get("/api/members/{member_id}", dependencies=[Depends(auth)])
def api_member(member_id: str):
    if not ctx.store.member_exists(member_id):
        raise HTTPException(404, "Không có thành viên này.")
    return member_summary(member_id)


@app.delete("/api/members/{member_id}", dependencies=[Depends(auth)])
def api_delete_member(member_id: str, keep_shifts: bool = False):
    ctx.store.delete_member(member_id, keep_shifts=keep_shifts)
    with ctx.glock:
        ctx.gallery.remove_member(member_id)
    with ctx.plock:
        ctx.presence.forget(member_id, keep_shifts=keep_shifts)
    ctx.handoff.pop(member_id, None)
    return {"ok": True}


@app.delete("/api/members/{member_id}/embeddings", dependencies=[Depends(auth)])
def api_delete_embeddings(member_id: str, source: Optional[str] = None):
    n = ctx.store.delete_embeddings(member_id, source)
    with ctx.glock:
        ctx.gallery.remove_member(member_id, source=source)
    return {"ok": True, "deleted": n}


# --------------------------------------------------------------------- đăng ký khuôn mặt
@app.post("/api/pose", dependencies=[Depends(auth)])
def api_pose(file: UploadFile = File(...), size: int = Form(320)):
    """Phát hiện nhanh + góc đầu (không tính embedding). Dùng cho HUD hướng dẫn xoay đầu."""
    img = read_image(file)
    if img is None:
        raise HTTPException(400, "Không đọc được ảnh.")
    h, w = img.shape[:2]
    faces = ctx.engine.analyze(img, det_size=max(160, min(960, size)), embed=False)
    return {"w": w, "h": h, "faces": [f.brief() for f in faces]}


@app.post("/api/enroll/frame", dependencies=[Depends(auth)])
def api_enroll_frame(file: UploadFile = File(...), member_id: str = Form(...), source: str = Form("door"),
                     step: str = Form(""), flip: bool = Form(True), dedup: float = Form(0.985),
                     occ: bool = Form(False)):
    """Lưu một khung hình từ HUD (mặt lớn nhất). Trả về lý do nếu bị từ chối."""
    member_id = check_member_id(member_id)
    if source not in ENROLL_GATES:
        raise HTTPException(400, "source phải là door hoặc room.")
    if not ctx.store.member_exists(member_id):
        raise HTTPException(404, "Chưa có thành viên này, hãy tạo trước.")
    img = read_image(file)
    if img is None:
        raise HTTPException(400, "Không đọc được ảnh.")
    face = ctx.engine.best_face(img, det_size=S("det_size_door") if source == "door" else S("det_size_room"), flip=flip, occ=occ)
    res = enroll_face(member_id, face, source, step, flip, dedup, uuid.uuid4().hex[:12])
    res["summary"] = member_summary(member_id)
    return res


@app.post("/api/enroll/batch", dependencies=[Depends(auth)])
@app.post("/enroll", dependencies=[Depends(auth)], include_in_schema=False)
def api_enroll_batch(member_id: str = Form(...), source: str = Form("door"), max_keep: int = Form(20),
                     flip: bool = Form(True), dedup: float = Form(0.93), occ: bool = Form(False),
                     files: List[UploadFile] = File(...)):
    """Đăng ký từ nhiều ảnh/khung hình video (ví dụ video quay bằng cam trần). Giữ tối đa max_keep ảnh tốt."""
    member_id = check_member_id(member_id)
    if source not in ENROLL_GATES:
        raise HTTPException(400, "source phải là door hoặc room.")
    if not ctx.store.member_exists(member_id):
        ctx.store.upsert_member(member_id, member_id, now().isoformat())
    kept, skipped = 0, defaultdict(int)
    for up in files:
        if kept >= max_keep:
            break
        img = read_image(up)
        if img is None:
            skipped["bad_image"] += 1
            continue
        face = ctx.engine.best_face(img, det_size=S("det_size_door") if source == "door" else S("det_size_room"), flip=flip, occ=occ)
        r = enroll_face(member_id, face, source, "batch", flip, dedup, uuid.uuid4().hex[:12])
        if r["accepted"]:
            kept += 1
        else:
            skipped[r["reason"]] += 1
    return {"member_id": member_id, "kept": kept, "skipped": dict(skipped),
            "total_for_member": ctx.gallery.count(member_id), "summary": member_summary(member_id)}


# ---- đăng ký kiểu CLB theo phiên (xem server/enrolling.py) -------------------------------------
REJECT_COUNTED = {"multi": "multiple_faces", "clipped": "clipped", "unsure": "low_det", "far": "small", "blurry": "blurry",
                  "no_face": "no_face", "bad_image": "bad_image"}


class SessionIn(BaseModel):
    member_id: str
    name: str = ""
    mode: str = "add"                # add (bổ sung vào mẫu đã có, mặc định) | replace (xoá mẫu cũ khi lưu)
    kind: str = "live"               # live (camera) | dataset (ảnh/video có sẵn)
    source: str = "door"


class FinishIn(BaseModel):
    target: Optional[int] = None
    flip: bool = True
    augment: str = "auto"            # auto (chỉ dataset và chỉ khi thiếu) | off | force
    verify: bool = True
    commit: bool = False


class UndoIn(BaseModel):
    member_id: str
    img_ids: List[str]


def get_session(sid: str) -> "enrolling.Session":
    sess = ctx.sessions.get(sid)
    if sess is None:
        raise HTTPException(404, "Phiên đăng ký đã hết hạn hoặc không tồn tại: bấm Bắt đầu để tạo phiên mới.")
    return sess


@app.post("/api/enroll/session", dependencies=[Depends(auth)])
def api_session_create(b: SessionIn):
    mid = check_member_id(b.member_id)
    if b.mode not in ("add", "replace") or b.kind not in ("live", "dataset") or b.source not in ENROLL_GATES:
        raise HTTPException(400, "mode phải là add/replace, kind là live/dataset, source là door/room.")
    exists = ctx.store.member_exists(mid)
    if b.kind == "live" and not exists:
        raise HTTPException(404, "Chưa có thành viên này, hãy tạo trước.")
    name = b.name.strip() or (ctx.store.member_name(mid) if exists else mid)
    sess = ctx.sessions.create(mid, name, b.mode, b.kind, b.source)
    return {"sid": sess.sid, "member_id": mid, "exists": exists, "ttl_s": enrolling.SESSION_TTL_S,
            "det_size": S("det_size_enroll"), "target": S("enroll_target")}


def _session_warning(sess) -> Optional[str]:
    """Cảnh báo sớm khi các khung của phiên giống một thành viên khác hơn chính người đang đăng ký."""
    cen = sess.centroid()
    if cen is None or sess.total() < 6:
        return None
    with ctx.glock:
        sc = ctx.gallery.scores(cen)
    own = sc.get(sess.member_id, -1.0)
    other_id, other = max(((k, v) for k, v in sc.items() if k != sess.member_id), key=lambda kv: kv[1], default=(None, -1.0))
    if other_id and other >= enrolling.LOOKS_LIKE_OTHER and other > own + 0.1:
        return f"Khuôn mặt này giống {ctx.store.member_name(other_id)} ({other:.2f}) hơn {sess.name}. Có chọn nhầm người không?"
    return None


def feed_session(sess, img: Optional[np.ndarray], label: str = "") -> dict:
    cfg = config.enroll_cfg(ctx.settings)
    if img is None:
        sess.rejects["bad_image"] += 1
        return {"state": "bad_image", "name": label, "kept": False}
    dataset = sess.kind == "dataset"
    info, cand = enrolling.observe(ctx.engine, img, cfg, int(S("det_size_door") if dataset else S("det_size_enroll")), keep_other=dataset)
    kept = False
    if cand is not None and not dataset and sess.total() >= 6:      # đổi người giữa chừng
        cen = sess.centroid()
        if cen is not None and float(cand["emb"] @ cen) < cfg["outlier_cos"]:
            info["state"], cand = "other_person", None
    if cand is not None:
        kept = sess.add(cand, cfg)
        info["fid"] = cand["fid"]
        if not kept:
            info["state"] = "dup"
    sess.frames += 1
    if info["state"] in REJECT_COUNTED:
        sess.rejects[REJECT_COUNTED[info["state"]]] += 1
    info["kept"] = kept
    if label:
        info["name"] = label
    return info


@app.post("/api/enroll/session/{sid}/frames", dependencies=[Depends(auth)])
def api_session_frames(sid: str, files: List[UploadFile] = File(...)):
    """Gửi một hoặc vài khung hình. Mỗi khung chỉ được xử lý MỘT lần: phát hiện + góc + embedding (nếu đạt cổng)."""
    import time
    sess = get_session(sid)
    t0 = time.perf_counter()
    with sess.lock:
        results = [feed_session(sess, read_image(up), up.filename or "") for up in files]
        warn = _session_warning(sess) if sess.kind == "live" else None
    return {"results": results, "counts": sess.counts(), "total": sess.total(), "frames": sess.frames, "warning": warn,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


@app.post("/api/enroll/session/{sid}/reset", dependencies=[Depends(auth)])
def api_session_reset(sid: str, direction: Optional[str] = None):
    sess = get_session(sid)
    if direction is not None and direction not in posebins.CLUB_DIRS:
        raise HTTPException(400, "Hướng không hợp lệ.")
    sess.reset(direction)
    return {"counts": sess.counts(), "total": sess.total()}


def compute_plan(sess, body: FinishIn) -> dict:
    cfg = config.enroll_cfg(ctx.settings)
    with ctx.glock:
        own, other_rows = [], []
        for i, (m, md) in enumerate(zip(ctx.gallery.ids, ctx.gallery.meta)):
            if m == sess.member_id:
                own.append({"emb": ctx.gallery.mat[i].copy(), "pitch": md.get("pitch"), "yaw": md.get("yaw"),
                            "step": md.get("step") or "", "img": md.get("img")})
            else:
                other_rows.append(i)
        other_mat = ctx.gallery.mat[other_rows].copy() if other_rows else np.zeros((0, 512), np.float32)
        other_ids = [ctx.gallery.ids[i] for i in other_rows]
    names = {m: ctx.store.member_name(m) for m in set(other_ids)}
    opts = {"target": body.target, "flip": body.flip, "augment": body.augment, "verify": body.verify}
    return enrolling.build_plan(sess, ctx.engine, cfg, own, other_mat, other_ids, names, opts,
                                MAX_IMAGES_PER_MEMBER, S("door_threshold"), S("door_margin"))


def commit_plan(sess) -> dict:
    plan = sess.pending
    if not plan or not plan["rows"]:
        raise HTTPException(409, plan["report"]["advice"] if plan else "Chưa chốt phiên.")
    mid = sess.member_id
    ts = now().isoformat()
    created = not ctx.store.member_exists(mid)
    if created:
        ctx.store.upsert_member(mid, sess.name or mid, ts)
    elif sess.name and sess.kind == "dataset":
        ctx.store.upsert_member(mid, sess.name, ts)
    rows = plan["rows"]
    with ctx.glock:
        if plan["replace"]:
            ctx.store.delete_embeddings(mid)
            ctx.gallery.remove_member(mid)
        ctx.store.add_embeddings_bulk([(mid, r["emb"], sess.source, r["pitch"], r["yaw"], ts, r["img"], r["step"]) for r in rows])
        ctx.gallery.add_many([(mid, r["emb"], {"source": sess.source, "pitch": r["pitch"], "yaw": r["yaw"],
                                               "img": r["img"], "step": r["step"]}) for r in rows])
    ctx.sessions.delete(sess.sid)
    rep = plan["report"]
    result = {"committed": True, "created": created, "report": rep, "img_ids": sorted({r["img"] for r in rows}),
              "total_for_member": ctx.gallery.count(mid), "summary": member_summary(mid)}
    del plan, rows
    trim()                       # trả RAM của phiên vừa xong (ảnh tạm, ma trận) cho hệ điều hành
    return result


@app.post("/api/enroll/session/{sid}/finish", dependencies=[Depends(auth)])
def api_session_finish(sid: str, body: FinishIn = Body(default=FinishIn())):
    """Chọn 20–30 mẫu tốt nhất từ các khung đã gửi, (dataset) bù augmentation nếu thiếu, kiểm tra độ tin cậy.
    commit=false: chỉ trả báo cáo (chưa ghi), gọi /commit để lưu. commit=true: ghi luôn."""
    if body.augment not in ("auto", "off", "force"):
        raise HTTPException(400, "augment phải là auto, off hoặc force.")
    sess = get_session(sid)
    with sess.lock:
        sess.pending = compute_plan(sess, body)
        if body.commit and sess.pending["rows"]:
            return commit_plan(sess)
        rep = sess.pending["report"]
    return {"committed": False, "report": rep}


@app.post("/api/enroll/session/{sid}/commit", dependencies=[Depends(auth)])
def api_session_commit(sid: str):
    sess = get_session(sid)
    with sess.lock:
        return commit_plan(sess)


@app.delete("/api/enroll/session/{sid}", dependencies=[Depends(auth)])
def api_session_delete(sid: str):
    return {"ok": True, "deleted": ctx.sessions.delete(sid)}


@app.post("/api/enroll/undo", dependencies=[Depends(auth)])
def api_enroll_undo(b: UndoIn):
    """Hoàn tác một lần lưu (bằng danh sách img_ids trả về lúc commit). Không khôi phục mẫu cũ nếu đã chọn 'replace'."""
    mid = check_member_id(b.member_id)
    n = ctx.store.delete_embeddings_by_img(mid, b.img_ids)
    with ctx.glock:
        ctx.gallery.remove_imgs(mid, b.img_ids)
    return {"ok": True, "deleted": n, "summary": member_summary(mid) if ctx.store.member_exists(mid) else None}


DATASET_REASONS = ("bad_image", "no_face", "multiple_faces", "clipped", "low_det", "small", "blurry", "looks_like_other", "outlier")


@app.post("/api/enroll/dataset", dependencies=[Depends(auth)])
def api_enroll_dataset(member_id: str = Form(...), name: str = Form(""), source: str = Form("door"),
                       target: int = Form(0), mode: str = Form("add"), flip: bool = Form(True), augment: str = Form("auto"),
                       verify: bool = Form(True), files: List[UploadFile] = File(...),
                       per_cell: int = Form(0), max_keep: int = Form(0), occ: bool = Form(False), dedup: float = Form(0)):
    """Nhập dataset CLB đã thu sẵn trong MỘT yêu cầu (tương thích bản cũ). Dùng đúng bộ chọn mẫu của đăng ký trực tiếp:
    chấm điểm -> loại 2 mặt/ngoại lai/giống người khác -> giữ 20–30 mẫu cân bằng 5 hướng -> augmentation nếu thiếu.
    per_cell/max_keep/occ/dedup chỉ giữ để tương thích, không còn tác dụng. Dataset lớn nên dùng /api/enroll/session."""
    mid = check_member_id(member_id)
    if source not in ENROLL_GATES or mode not in ("add", "replace") or augment not in ("auto", "off", "force"):
        raise HTTPException(400, "Tham số source/mode/augment không hợp lệ.")
    sess = ctx.sessions.create(mid, name.strip() or (ctx.store.member_name(mid) if ctx.store.member_exists(mid) else mid),
                               mode, "dataset", source)
    try:
        with sess.lock:
            for up in files:
                feed_session(sess, read_image(up), up.filename or "")
            sess.pending = compute_plan(sess, FinishIn(target=target or None, flip=flip, augment=augment, verify=verify))
            rep = sess.pending["report"]
            if not sess.pending["rows"]:
                return {"member_id": mid, "kept": 0, "skipped": rep["rejected"], "warnings": rep["warnings"], "created": False,
                        "total_for_member": ctx.gallery.count(mid), "summary": member_summary(mid) if ctx.store.member_exists(mid) else None,
                        "report": rep}
            out = commit_plan(sess)
    finally:
        ctx.sessions.delete(sess.sid)
    return {"member_id": mid, "kept": rep["kept"], "skipped": rep["rejected"], "warnings": rep["warnings"], "created": out["created"],
            "total_for_member": out["total_for_member"], "summary": out["summary"], "report": rep, "img_ids": out["img_ids"]}


# --------------------------------------------------------------------- thử nhận diện / hiệu chỉnh
@app.post("/api/recognize", dependencies=[Depends(auth)])
def api_recognize(file: UploadFile = File(...), context: str = Form("room"), stranger: bool = Form(False)):
    """Nhận diện mọi mặt trong ảnh, trả lý do chấp nhận/từ chối. stranger=1: lưu các mặt này làm mẫu người lạ."""
    if context not in ("door", "room"):
        raise HTTPException(400, "context phải là door hoặc room.")
    img = read_image(file)
    if img is None:
        raise HTTPException(400, "Không đọc được ảnh.")
    faces = ctx.engine.analyze(img, det_size=S("det_size_door") if context == "door" else S("det_size_room"))
    out, saved = [], 0
    for f in faces:
        d = recognize_face(f, context)
        d.update(f.brief())
        out.append(d)
        if stranger and f.emb is not None:
            ctx.store.add_stranger(f.emb, f.pitch, f.yaw, context, now().isoformat())
            saved += 1
    return {"w": img.shape[1], "h": img.shape[0], "faces": out, "stranger_saved": saved}


@app.get("/api/calibration", dependencies=[Depends(auth)])
def api_calibration():
    rows = ctx.store.all_embeddings()
    rep = calibration.analyze(rows, ctx.store.strangers(), S("high_angle_pitch"), S("high_angle_yaw"))
    rep["current"] = {k: S(k) for k in ("door_threshold", "room_threshold", "room_threshold_high",
                                        "door_margin", "room_margin")}
    return rep


@app.delete("/api/strangers", dependencies=[Depends(auth)])
def api_clear_strangers():
    return {"deleted": ctx.store.clear_strangers()}


@app.get("/api/settings", dependencies=[Depends(auth)])
def api_get_settings():
    return {"values": ctx.settings, "spec": config.describe()}


@app.post("/api/settings", dependencies=[Depends(auth)])
def api_set_settings(values: Dict[str, Any] = Body(...)):
    new = dict(ctx.settings)
    for k, v in values.items():
        try:
            new[k] = config.coerce(k, v)
        except ValueError as e:
            raise HTTPException(400, str(e))
    if new["close_hour"] <= new["open_hour"]:
        raise HTTPException(400, "Giờ đóng cửa phải sau giờ mở cửa.")
    ctx.settings = new
    ctx.store.kv_set("settings", new)
    apply_settings()
    return {"values": ctx.settings}


# --------------------------------------------------------------------- check-in (cam cửa)
@app.post("/api/checkin", dependencies=[Depends(auth)])
@app.post("/checkin", dependencies=[Depends(auth)], include_in_schema=False)
def checkin(files: List[UploadFile] = File(...)):
    """Nhận một burst vài khung hình; bỏ phiếu để quyết định danh tính."""
    votes: Dict[str, list] = defaultdict(list)
    usable, frames = 0, []
    for up in files:
        img = read_image(up)
        if img is None:
            continue
        f = ctx.engine.best_face(img, det_size=S("det_size_door"))
        if f is None:
            frames.append({"reason": "no_face"})
            continue
        if f.width < DOOR_MIN_W:
            frames.append({"reason": "too_small", "width": f.width})
            continue
        if f.yaw is not None and (abs(f.yaw) > DOOR_MAX_YAW or abs(f.pitch) > DOOR_MAX_PITCH):
            frames.append({"reason": "extreme_pose", "pitch": round(f.pitch), "yaw": round(f.yaw)})
            continue
        usable += 1
        d = recognize_face(f, "door")
        frames.append({"reason": d["reason"], "score": d["score"], "margin": d["margin"], "best": d["best_id"]})
        if d["member_id"]:
            votes[d["member_id"]].append((d["score"], d["margin"]))
    if usable == 0:
        return {"status": "no_usable_face", "frames": frames}
    if not votes:
        raise_alert("alert_unknown_door", "Người lạ trước cửa: có mặt nhưng không khớp thành viên nào")
        return {"status": "unknown", "usable_frames": usable, "frames": frames}
    who, vs = max(votes.items(), key=lambda kv: len(kv[1]))
    if len(vs) < int(S("door_votes")):
        raise_alert("alert_unknown_door", "Cửa nhận diện chưa chắc chắn (thiếu phiếu)", min_gap_s=120)
        return {"status": "unknown", "usable_frames": usable, "best_votes": len(vs), "frames": frames}
    ts = now()
    with ctx.plock:
        result = ctx.presence.checkin(who, ts)
        on_shift = ctx.presence.on_shift(who, ts)
    if result == "checkin":
        ctx.handoff[who] = ts
    return {"status": result, "member_id": who, "name": ctx.store.member_name(who),
            "score": round(float(np.mean([v[0] for v in vs])), 3), "votes": len(vs),
            "time": ts.isoformat(timespec="seconds"), "on_shift": on_shift, "frames": frames}


# --------------------------------------------------------------------- cam trong phòng
@app.post("/api/room/frame", dependencies=[Depends(auth)])
@app.post("/observe", dependencies=[Depends(auth)], include_in_schema=False)
def room_frame(file: UploadFile = File(...)):
    """Chế độ không theo dõi người: nhận một khung hình, nhận diện mọi mặt thấy được."""
    img = read_image(file)
    if img is None:
        raise HTTPException(400, "Không đọc được ảnh.")
    ts, out = now(), []
    need = int(S("room_votes"))
    for f in ctx.engine.analyze(img, det_size=S("det_size_room")):
        d = recognize_face(f, "room")
        who = d["member_id"]
        confirmed = False
        if who:
            vs = [t for t in ctx.frame_votes.get(who, []) if (ts - t).total_seconds() <= 15] + [ts]
            ctx.frame_votes[who] = vs
            if len(vs) >= need:
                confirmed = True
                with ctx.plock:
                    ctx.presence.observe(who, ts)
        d.update(f.brief())
        d["confirmed"] = confirmed
        out.append(d)
    with ctx.plock:
        occ = ctx.presence.occupants()
    ctx.room.update(persons=len(out), ts=ts.isoformat(timespec="seconds"))
    return {"w": img.shape[1], "h": img.shape[0], "faces": out, "occupants": occ}


@app.post("/api/room/identify", dependencies=[Depends(auth)])
def room_identify(track_ids: str = Form(...), files: List[UploadFile] = File(...)):
    """Nhận ảnh cắt (đầu-vai) của các track chưa biết danh tính; trả kết quả nhận diện cho từng track."""
    ids = [int(x) for x in track_ids.split(",") if x.strip() != ""]
    if len(ids) != len(files):
        raise HTTPException(400, "Số track_ids phải bằng số ảnh.")
    results = []
    for tid, up in zip(ids, files):
        img = read_image(up)
        res = {"track_id": tid, "face_found": False, "member_id": None, "score": 0.0}
        if img is not None:
            faces = ctx.engine.analyze_crop(img)
            if faces:
                f = faces[0]
                d = recognize_face(f, "room")
                res.update(face_found=True, member_id=d["member_id"], score=d["score"], margin=d["margin"],
                           reason=d["reason"], high=d["high_angle"], pitch=f.brief()["pitch"], yaw=f.brief()["yaw"])
        results.append(res)
    return {"results": results}


class IdentIn(BaseModel):
    member_id: str
    score: float = 0.0
    source: str = "face"


class RoomUpdateIn(BaseModel):
    persons: int = 0
    strangers: int = 0
    identified: List[IdentIn] = Field(default_factory=list)
    bound: List[str] = Field(default_factory=list)


@app.post("/api/room/update", dependencies=[Depends(auth)])
def room_update(u: RoomUpdateIn):
    """Cam trần báo định kỳ: số người, ai đang thấy. Trả về danh sách người vừa check-in chờ gán track."""
    ts = now()
    with ctx.plock:
        for it in u.identified:
            if ctx.store.member_exists(it.member_id):
                ctx.presence.observe(it.member_id, ts)
    for m in u.bound:
        ctx.handoff.pop(m, None)
    if u.strangers > 0:
        raise_alert("alert_stranger_room", f"Phòng có {u.strangers} người chưa nhận diện được", min_gap_s=300)
    ctx.room.update(persons=u.persons, strangers=u.strangers, ts=ts.isoformat(timespec="seconds"),
                    identified=[i.member_id for i in u.identified])
    pending = [m for m, t0 in sorted(ctx.handoff.items(), key=lambda kv: kv[1])
               if (ts - t0).total_seconds() <= HANDOFF_TTL_S]
    return {"ok": True, "pending": pending}


# --------------------------------------------------------------------- trạng thái / ca trực / báo cáo
@app.get("/api/status", dependencies=[Depends(auth)])
def api_status():
    ts = now()
    names = dict(ctx.store.members())
    with ctx.plock:
        people = []
        for m, st in ctx.presence.state.items():
            if st.status in (PRESENT, AWAY):
                people.append({"member_id": m, "name": names.get(m, m), "status": st.status,
                               "last_seen": st.last_seen.isoformat(timespec="seconds") if st.last_seen else None,
                               "since": (st.away_from or st.checked_in_at).isoformat(timespec="seconds")
                               if (st.away_from or st.checked_in_at) else None,
                               "on_shift": ctx.presence.on_shift(m, ts)})
    day, lo, hi = day_bounds(ts.date())
    shifts = []
    for sid, m, s, e in ctx.store.shifts_between(lo, hi):
        st_, en_ = datetime.fromisoformat(s), datetime.fromisoformat(e)
        ab = ctx.store.absences_for(m, s, e)
        shifts.append({"id": sid, "member_id": m, "name": names.get(m, m), "start": s, "end": e,
                       "state": shift_state(m, st_, en_, ts), "status": ctx.presence.status_of(m),
                       "absences": [{"from": a, "to": b, "minutes": mins} for a, b, mins in ab]})
    events = [{"ts": t, "kind": k, "member_id": m, "name": names.get(m, m or ""), "detail": d}
              for t, k, m, d in ctx.store.recent_events(30)]
    return {"now": ts.isoformat(timespec="seconds"), "people": people, "shifts": shifts, "events": events,
            "room": ctx.room, "pending_handoff": list(ctx.handoff),
            "open": S("open_hour") <= ts.hour < S("close_hour"),
            "counts": {"members": len(names), "embeddings": len(ctx.gallery.ids), "strangers": ctx.store.count_strangers()},
            "engine": {"providers": ctx.engine.providers, "model": ctx.engine.model_name, "db": ctx.store.kind},
            "settings": {k: S(k) for k in ("open_hour", "close_hour", "grace_s")}}


class ShiftIn(BaseModel):
    member_id: str
    start: datetime
    end: datetime


@app.get("/api/shifts", dependencies=[Depends(auth)])
def api_shifts(day: Optional[date] = None):
    day, lo, hi = day_bounds(day)
    names, ts = dict(ctx.store.members()), now()
    return {"day": str(day), "shifts": [
        {"id": i, "member_id": m, "name": names.get(m, m), "start": s, "end": e,
         "state": shift_state(m, datetime.fromisoformat(s), datetime.fromisoformat(e), ts)}
        for i, m, s, e in ctx.store.shifts_between(lo, hi)]}


@app.post("/api/shifts", dependencies=[Depends(auth)])
@app.post("/shifts", dependencies=[Depends(auth)], include_in_schema=False)
def add_shift(s: ShiftIn):
    st, en = to_local_naive(s.start), to_local_naive(s.end)
    if en <= st:
        raise HTTPException(400, "Giờ kết thúc phải sau giờ bắt đầu.")
    if st.date() != en.date():
        raise HTTPException(400, "Mỗi ca nằm trong một ngày; hãy tách ca qua đêm thành hai ca.")
    if not ctx.store.member_exists(s.member_id):
        raise HTTPException(404, "Chưa có thành viên này.")
    _d, lo, hi = day_bounds(st.date())
    for _sid, m, a, b in ctx.store.shifts_between(lo, hi):
        if m == s.member_id and a < en.isoformat() and b > st.isoformat():
            raise HTTPException(409, "Ca này trùng hoặc chồng lên một ca đã có của người này.")
    sid = ctx.store.add_shift(s.member_id, st.isoformat(), en.isoformat())
    with ctx.plock:
        ctx.presence.add_shift(Shift(s.member_id, st, en))
    return {"ok": True, "id": sid}


@app.delete("/api/shifts/{shift_id}", dependencies=[Depends(auth)])
def delete_shift(shift_id: int):
    r = ctx.store.get_shift(shift_id)
    if not r:
        raise HTTPException(404, "Không có ca này.")
    ctx.store.delete_shift(shift_id)
    with ctx.plock:
        ctx.presence.remove_shift(r[1], datetime.fromisoformat(r[2]), datetime.fromisoformat(r[3]))
    return {"ok": True}


def build_report(day: Optional[date]) -> dict:
    day, lo, hi = day_bounds(day)
    names = dict(ctx.store.members())
    ts = now()
    events_raw = ctx.store.events_between(lo, hi)
    first_in: Dict[str, str] = {}
    for t, k, m, _ in events_raw:
        if k in ("checkin", "seen_without_checkin") and m and m not in first_in:
            first_in[m] = t
    rows = []
    for sid, mid, s, e in ctx.store.shifts_between(lo, hi):
        st_, en_ = datetime.fromisoformat(s), datetime.fromisoformat(e)
        ab = [{"from": datetime.fromisoformat(a).strftime("%H:%M"), "to": datetime.fromisoformat(b).strftime("%H:%M"),
               "minutes": m, "ongoing": False} for a, b, m in ctx.store.absences_for(mid, s, e)]
        with ctx.plock:
            stt = ctx.presence.state.get(mid)
            away_from = stt.away_from if (stt and stt.status == AWAY) else None
        if away_from and st_ <= ts < en_:                      # đang vắng, chưa quay lại
            start = max(away_from, st_)
            ab.append({"from": start.strftime("%H:%M"), "to": "đang vắng", "minutes": round((ts - start).total_seconds() / 60, 1),
                       "ongoing": True})
        seen = first_in.get(mid)
        rows.append({"member_id": mid, "name": names.get(mid, mid),
                     "shift": [st_.strftime("%H:%M"), en_.strftime("%H:%M")],
                     "first_seen": seen[11:16] if seen else None,
                     "not_seen": (seen is None and ts >= st_),          # đã tới giờ ca mà chưa thấy check-in
                     "absences": ab, "total_minutes": round(sum(x["minutes"] for x in ab), 1)})
    events = [{"ts": t, "kind": k, "member_id": m, "name": names.get(m, m or "")} for t, k, m, _ in events_raw]
    with ctx.plock:
        occ = ctx.presence.occupants()
    return {"day": str(day), "shifts": rows, "events": events, "occupants_now": occ}


@app.get("/api/report", dependencies=[Depends(auth)])
@app.get("/report", dependencies=[Depends(auth)], include_in_schema=False)
def api_report(day: Optional[date] = None):
    return build_report(day)


def _csv_safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@app.get("/api/report.csv", dependencies=[Depends(auth)])
def api_report_csv(day: Optional[date] = None):
    rep = build_report(day)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Ngày", "Mã", "Tên", "Ca từ", "Ca đến", "Check-in đầu", "Vắng từ", "Vắng đến", "Số phút vắng", "Tổng phút vắng trong ca"])
    for r in rep["shifts"]:
        head = [rep["day"], _csv_safe(r["member_id"]), _csv_safe(r["name"]), *r["shift"], r["first_seen"] or "KHÔNG THẤY"]
        if not r["absences"]:
            w.writerow([*head, "", "", "", 0])
        for a in r["absences"]:
            w.writerow([*head, a["from"], a["to"], a["minutes"], r["total_minutes"]])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="bao-cao-{rep["day"]}.csv"'})


@app.get("/api/backup", dependencies=[Depends(auth)])
@app.get("/backup", dependencies=[Depends(auth)], include_in_schema=False)
def backup():
    if ctx.store.kind != "sqlite":
        raise HTTPException(400, "Đang dùng Postgres: tải bản sao lưu JSON ở /api/export.")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    ctx.store.backup_to(tmp.name)
    return FileResponse(tmp.name, filename="club-backup.db", background=BackgroundTask(os.unlink, tmp.name))


@app.get("/api/export", dependencies=[Depends(auth)])
def api_export():
    """Sao lưu toàn bộ (thành viên + vector khuôn mặt + ca + lịch sử + cảnh báo) dạng JSON; dùng được cho cả SQLite và Postgres."""
    data = ctx.store.export_all()
    return Response(json.dumps(data), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="club-export-{now().date()}.json"'})


app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
