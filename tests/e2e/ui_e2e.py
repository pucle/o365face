"""E2E trình duyệt thật (Chromium + camera giả). python tests/e2e/ui_e2e.py CAM.y4m [URL] [TOKEN] [OUTDIR]"""
import sys, time, os
from playwright.sync_api import sync_playwright
cam = sys.argv[1]; URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:7860"
TOKEN = sys.argv[3] if len(sys.argv) > 3 else "dev"; OUT = sys.argv[4] if len(sys.argv) > 4 else "."
bad = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, info)
    if not c: bad.append(n)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.getenv("CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"), args=[
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", f"--use-file-for-fake-video-capture={cam}", "--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}); ctx.grant_permissions(["camera"])
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(URL + "/ui/"); pg.evaluate(f"localStorage.setItem('apiToken','{TOKEN}')"); pg.goto(URL + "/ui/#status"); pg.reload()
    pg.wait_for_selector("#stCounts"); time.sleep(1.5)
    check("status page loads", pg.inner_text("#stOpen") != "–", pg.inner_text("#stOpen"))
    pg.click("a[href='#members']"); pg.fill("#mId", "phuc"); pg.fill("#mName", "Phúc"); pg.click("#fMember button"); time.sleep(1)
    check("member created", "Phúc" in pg.inner_text("#memberList"))
    pg.click("a[href='#enroll']"); time.sleep(1)
    check("enroll page is one screen: Bắt đầu button + collapsed Nâng cao", pg.is_visible("#eStart") and not pg.locator("details.adv").evaluate("e => e.open"))
    check("no consent checkbox on enroll page", pg.locator("#eConsent").count() == 0)
    pg.select_option("#eMember", "phuc"); T_START = time.time(); pg.click("#eStart")
    pg.wait_for_selector("#enStage:not(.hidden)", timeout=15000)
    check("5 phase chips", pg.locator("#eChips .pchip").count() == 5, pg.inner_text("#eChips").replace("\n", " "))
    t0 = time.time(); ok = False
    while time.time() - t0 < 60:
        if pg.locator("#eChips .pchip.done").count() >= 1: ok = True; break
        time.sleep(1)
    print("TIMING front phase done after %.1f s (gồm đếm ngược 3 s)" % (time.time() - T_START))
    pg.screenshot(path=f"{OUT}/hud.png")
    check("front phase auto-captured (continuous, no click)", ok, pg.inner_text("#eChips").replace("\n", " "))
    txt = pg.inner_text("#eText"); check("instruction advances to next direction", any(w in txt for w in ("TRÁI", "Quay", "Tiếp", "trái")), txt)
    pg.wait_for_selector("#enResult:not(.hidden)", timeout=150000)   # camera giả chỉ nhìn thẳng: 4 chặng còn lại hết giờ -> báo yếu
    print("TIMING start -> result screen %.1f s (4 chặng sau chỉ chờ hết giờ vì camera giả chỉ nhìn thẳng)" % (time.time() - T_START))
    pg.screenshot(path=f"{OUT}/enroll_result.png")
    res = pg.inner_text("#enResult")
    check("result shows verdict and weak directions", "Nên bổ sung" in res and "thiếu" in res, res[:200].replace("\n", " "))
    check("redo-weak button offered", pg.is_visible("#eRedoWeak"))
    check("thumbnails kept in browser memory", pg.locator("#rDirs img").count() >= 1,
          pg.evaluate("JSON.stringify([Object.keys(EnrollPage._state.thumbs).length, EnrollPage._state.report.chosen.map(c=>c.fid)])"))
    pg.click("#eSave"); pg.wait_for_selector("#eNext:not(.hidden)", timeout=15000)
    check("saved", "Đã lưu" in pg.inner_text("#rTitle"))
    pg.click("a[href='#members']"); time.sleep(1.5)
    ml = pg.inner_text("#memberList"); check("members page shows progress toward target (not x/42)", "mẫu gốc" in ml and "/ 24" in ml and "/42" not in ml, ml[:120].replace("\n", " "))
    pg.click("details.more summary"); pg.click("a[href='#lab']"); pg.select_option("#lContext", "door"); pg.click("#lStart"); time.sleep(6)
    lab = pg.inner_text("#lList"); pg.screenshot(path=f"{OUT}/lab.png")
    check("lab recognizes member", "Phúc" in lab, lab[:100])
    pg.click("#lStop")
    pg.click("details.more summary"); pg.click("a[href='#door']"); pg.click("#dStart"); t0 = time.time(); got = False
    while time.time() - t0 < 30:
        if "check-in" in pg.inner_text("#dBanner") and "Phúc" in pg.inner_text("#dBanner"): got = True; break
        time.sleep(1)
    pg.screenshot(path=f"{OUT}/door.png"); check("door trigger -> check-in", got, pg.inner_text("#dBanner"))
    pg.click("#dStop")
    pg.click("a[href='#shifts']"); time.sleep(1); pg.click("#fShift button"); time.sleep(1)
    check("shift added", "Phúc" in pg.inner_text("#rTable"), pg.inner_text("#rTable")[:100])
    pg.click("a[href='#status']"); time.sleep(2); pg.screenshot(path=f"{OUT}/status.png")
    check("status shows person", "Phúc" in pg.inner_text("#stPeople"), pg.inner_text("#stPeople")[:80])
    pg.click("a[href='#settings']"); time.sleep(2); pg.screenshot(path=f"{OUT}/settings.png")
    check("settings form", pg.locator("#fSettings input").count() >= 10, pg.locator("#fSettings input").count())
    check("no JS errors", not errs, errs[:3])
    b.close()
print("E2E OK" if not bad else "E2E FAILED: %s" % bad); sys.exit(1 if bad else 0)
