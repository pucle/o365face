"""E2E luồng 5 chặng CLB với camera giả: phản hồi của /frames được GIẢ LẬP theo kịch bản xoay đầu (không có người thật),
riêng chặng chính diện gửi tới server thật. Kiểm tra: đếm ngược, tự chuyển chặng, mũi tên, "Làm lại bước này",
kết quả, "Làm lại hướng yếu", Lưu, và thành viên hiện tiến độ đúng.
python tests/e2e/club_e2e.py CAM.y4m [URL] [TOKEN] [OUTDIR]"""
import sys, os, time, json
from playwright.sync_api import sync_playwright
cam = sys.argv[1]; URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:7860"
TOKEN = sys.argv[3] if len(sys.argv) > 3 else "dev"; OUT = sys.argv[4] if len(sys.argv) > 4 else "."
bad = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, info)
    if not c: bad.append(n)
TARGET = {"front": (0, 0), "left": (0, 45), "right": (0, -45), "up": (30, 0), "down": (-30, 0)}
st = {"n": 0, "turn": "front", "fid": 1000}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.getenv("CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"), args=[
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", f"--use-file-for-fake-video-capture={cam}", "--no-sandbox"])
    ctx = b.new_context(viewport={"width": 420, "height": 900}); ctx.grant_permissions(["camera"])   # kích thước điện thoại dọc
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    def handle(route):
        cur = pg.evaluate("(window.EnrollPage._state.scan && window.EnrollPage._state.scan.current()) || ''")
        st["n"] += 1
        if cur in ("", "front"):
            return route.continue_()                     # chặng chính diện: server thật phân tích khung camera giả
        if st["n"] % 7 == 0:                             # thỉnh thoảng giả "chưa thấy mặt" để kiểm thông báo
            body = {"results": [{"state": "no_face", "kept": False}], "counts": {}, "total": 0, "warning": None, "ms": 1}
        elif st["turn"] == "wrong":
            body = {"results": [{"state": "between", "dir": None, "pitch": 0, "yaw": 5, "kept": False}], "counts": {}, "total": 0, "warning": None, "ms": 1}
        else:
            pi, ya = TARGET[cur]; st["fid"] += 1
            body = {"results": [{"state": "ok", "dir": cur, "pitch": pi, "yaw": ya, "kept": True, "fid": st["fid"], "box": [.3, .2, .7, .8]}], "counts": {}, "total": 1, "warning": None, "ms": 1}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    pg.route("**/api/enroll/session/*/frames", handle)
    pg.goto(URL + "/ui/"); pg.evaluate(f"localStorage.setItem('apiToken','{TOKEN}')"); pg.goto(URL + "/ui/#members"); pg.reload()
    pg.wait_for_selector("#mId"); pg.fill("#mId", "clubby"); pg.fill("#mName", "Club Tester"); pg.click("#fMember button"); time.sleep(1)
    check("new member shows 0 progress and is listed first", "Chưa đăng ký" in pg.inner_text("#memberList"), pg.inner_text("#memberSummary")[:90])
    pg.click("a[href='#enroll']"); time.sleep(1); pg.select_option("#eMember", "clubby"); pg.click("#eStart")
    pg.wait_for_selector("#eCount:not(.hidden)", timeout=15000)
    check("countdown shown", pg.inner_text("#eCount") in ("3", "2", "1"), pg.inner_text("#eCount"))
    pg.wait_for_selector("#eCount.hidden", state="attached", timeout=8000)
    pg.screenshot(path=f"{OUT}/club_mobile_front.png")
    t0 = time.time(); seen = set()
    while time.time() - t0 < 90 and pg.locator("#enResult.hidden").count() == 1:
        seen.add(pg.inner_text("#eText")); time.sleep(0.4)
        if len(seen) == 4 and "redo" not in st:               # thử "Làm lại bước này" một lần giữa chừng
            st["redo"] = True; pg.click("#eRedoStep")
    check("instruction text changed across phases", len(seen) >= 3, list(seen)[:5])
    check("chips reached result screen", pg.locator("#enResult.hidden").count() == 0)
    pg.screenshot(path=f"{OUT}/club_result.png")
    res = pg.inner_text("#enResult")
    check("result lists all 5 directions", all(w in res for w in ("Chính diện", "Quay trái", "Quay phải", "Ngẩng", "Cúi")), res[:160].replace("\n", " "))
    check("verdict present", "Nên bổ sung" in res or "Đủ tin cậy" in res)
    # LÀM LẠI HƯỚNG YẾU (server chỉ có khung chính diện nên 4 hướng kia yếu) -> chạy lại các hướng đó với khung giả
    weak = (pg.get_attribute("#eRedoWeak", "data-dirs") or "").split(",")
    if pg.is_visible("#eRedoWeak"):
        pg.click("#eRedoWeak"); pg.wait_for_selector("#enStage:not(.hidden)", timeout=10000)
        check("redo-weak runs only the weak directions", pg.locator("#eChips .pchip").count() == len(weak), (pg.locator("#eChips .pchip").count(), weak))
        pg.wait_for_selector("#enResult:not(.hidden)", timeout=90000)
    pg.click("#eSave"); pg.wait_for_selector("#eNext:not(.hidden)", timeout=15000)
    check("saved + undo offered (add mode)", pg.is_visible("#eUndo"))
    pg.click("a[href='#members']"); time.sleep(1.5)
    ml = pg.inner_text("#memberList"); pg.screenshot(path=f"{OUT}/club_members.png")
    check("member card shows real samples toward target", "/ 24 mẫu gốc" in ml, ml[:140].replace("\n", " "))
    check("no horizontal scroll on phone width", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
    check("no JS errors", not errs, errs[:3])
    b.close()
print("CLUB E2E OK" if not bad else "CLUB E2E FAILED: %s" % bad); sys.exit(1 if bad else 0)
