"""Nhập dataset khuôn mặt CLB đã thu sẵn (thư mục hoặc file .zip), mỗi thành viên một thư mục:

    dataset/
      Nguyen Van An/   anh1.jpg  anh2.jpg  quay-trai.mp4 ...      (tên thư mục = tên hoặc mã thành viên)
      tran_binh/       ...

Mỗi thành viên nên có: nhìn chính diện, quay trái ~45°, quay phải ~45°, ngẩng và cúi ~45° (ảnh hoặc video).
    python tools/import_dataset.py dataset/            --url https://user-space.hf.space --token XXX --yes-consent
    python tools/import_dataset.py dataset.zip --dry-run
Thư mục khớp thành viên có sẵn (theo mã hoặc tên, bỏ dấu); không khớp thì TẠO MỚI nếu có --create (mặc định bật).
Video: lấy khung hình mỗi ~0.3 giây (tối đa --frames), bỏ khung mờ. Server giữ tối đa --per-cell mẫu mỗi ô góc."""
import argparse, os, re, sys, tempfile, unicodedata, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMG = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VID = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"}
UNSUPPORTED = {".heic", ".heif"}


def norm(s):
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def slug(s):
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "member"


def match_member(folder, members):
    """members: [(id, name)] -> (id, name) | None. Khớp đúng (bỏ dấu), hoặc duy nhất một người chứa nhau."""
    n = norm(folder)
    for mid, name in members:
        if n and n in (norm(mid), norm(name)):
            return mid, name
    c = [(m, nm) for m, nm in members if n and len(norm(nm)) >= 3 and (norm(nm) in n or n in norm(nm))]
    return c[0] if len(c) == 1 else None


def group(paths):
    """paths: danh sách đường dẫn tương đối (a/b/c.jpg) -> {thư_mục_thành_viên: [paths]}."""
    deep = any(len(p.replace("\\", "/").split("/")) >= 3 for p in paths)
    out = {}
    for p in paths:
        parts = p.replace("\\", "/").split("/")
        if len(parts) < 2:
            continue
        out.setdefault(parts[1] if deep else parts[0], []).append(p)
    return out


def video_frames(path, max_frames, step_s=0.3):
    import cv2
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if total <= 0:
        return []
    n = max(1, min(max_frames, int(total / fps / step_s) or 1))
    cand = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + .5) / n))
        ok, fr = cap.read()
        if ok:
            cand.append((cv2.Laplacian(cv2.cvtColor(cv2.resize(fr, (320, int(fr.shape[0] * 320 / fr.shape[1]))), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var(), fr))
    if len(cand) > 8:                                   # bỏ ~20% khung mờ nhất
        thr = sorted(c[0] for c in cand)[len(cand) // 5]
        cand = [c for c in cand if c[0] >= thr]
    h = cand[0][1].shape[0] if cand else 0
    out = []
    for _, fr in cand:
        s = min(1.0, 1280 / max(fr.shape[:2]))
        out.append(cv2.imencode(".jpg", cv2.resize(fr, None, fx=s, fy=s) if s < 1 else fr, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes())
    return out


def main():
    from client import net
    ap = argparse.ArgumentParser(); ap.add_argument("src"); net.add_common(ap)
    ap.add_argument("--dataset-source", default="door", choices=["door", "room"], dest="gate")
    ap.add_argument("--target", type=int, default=24, help="số mẫu gốc giữ lại mỗi người (20-30)")
    ap.add_argument("--mode", default="add", choices=["add", "replace"], help="add: bổ sung vào mẫu đã có (mặc định); replace: thay thế")
    ap.add_argument("--augment", default="auto", choices=["auto", "off"], help="auto: chỉ bù augmentation khi thiếu dữ liệu")
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--no-create", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes-consent", action="store_true", help="(không còn bắt buộc, giữ để tương thích lệnh cũ)")
    a = ap.parse_args()
    root, tmp = a.src, None
    if a.src.lower().endswith(".zip"):
        tmp = tempfile.TemporaryDirectory(); zipfile.ZipFile(a.src).extractall(tmp.name); root = tmp.name
    rel = [os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs if not f.startswith(".")]
    groups = group(sorted(rel))
    if not a.dry_run:
        srv = net.from_env(a)
        members = [(m["member_id"], m["name"]) for m in srv.get("/api/members")["members"]]
    else:
        members = []
    total = {"kept": 0}
    for folder, paths in sorted(groups.items()):
        imgs = [p for p in paths if os.path.splitext(p)[1].lower() in IMG]
        vids = [p for p in paths if os.path.splitext(p)[1].lower() in VID]
        bad = [p for p in paths if os.path.splitext(p)[1].lower() in UNSUPPORTED]
        hit = match_member(folder, members)
        mid, name = hit if hit else (slug(folder), folder.strip())
        print(f"\n== {folder}  ->  {mid} ({'có sẵn' if hit else 'TẠO MỚI'}): {len(imgs)} ảnh, {len(vids)} video" + (f", {len(bad)} file HEIC bị bỏ (hãy xuất sang JPG)" if bad else ""))
        if a.dry_run or (not hit and a.no_create):
            continue
        blobs = [(os.path.basename(p), open(os.path.join(root, p), "rb").read()) for p in sorted(imgs)]
        for p in sorted(vids):
            fr = video_frames(os.path.join(root, p), a.frames)
            print(f"   video {os.path.basename(p)}: {len(fr)} khung")
            blobs += [(f"{os.path.basename(p)}#{i}.jpg", b) for i, b in enumerate(fr)]
        sess = srv.post("/api/enroll/session", json={"member_id": mid, "name": name, "mode": a.mode, "kind": "dataset", "source": a.gate})
        sid = sess["sid"]
        try:
            for i in range(0, len(blobs), 8):
                srv.post(f"/api/enroll/session/{sid}/frames", files=[("files", (n, b)) for n, b in blobs[i:i + 8]])
            r = srv.post(f"/api/enroll/session/{sid}/finish", json={"commit": True, "target": a.target, "augment": a.augment})
        except Exception:
            try:
                srv.delete(f"/api/enroll/session/{sid}")
            except Exception:
                pass
            raise
        rep = r["report"]
        for w in rep.get("warnings", []):
            print("   ⚠", w)
        total["kept"] += rep["kept"] if r.get("committed") else 0
        dirs = ", ".join(f"{k}={v}" for k, v in (rep.get("per_dir_total") or rep.get("per_dir") or {}).items())
        print(f"   {'lưu' if r.get('committed') else 'KHÔNG lưu'} {rep['kept']} ảnh gốc, {rep.get('flips', 0)} bản lật, {rep.get('aug', 0)} augmentation; bỏ qua {rep['rejected']}")
        print(f"   theo hướng: {dirs}\n   kết luận: {rep['verdict']}" + ("" if rep.get("ok") else f" — {rep['advice']}"))
    print(f"\nXong. Tổng {total['kept']} ảnh được lưu." if not a.dry_run else "\n(dry-run: chưa gửi gì)")


if __name__ == "__main__":
    main()
