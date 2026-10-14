"""E2E trang Nhập dataset: python tests/e2e/import_e2e.py DATASET_DIR [URL] [TOKEN] [OUTDIR]
DATASET_DIR có các thư mục con (xem tools/import_dataset.py)."""
import sys, os, time
from playwright.sync_api import sync_playwright
ds = sys.argv[1]; URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:7860"
TOKEN = sys.argv[3] if len(sys.argv) > 3 else "dev"; OUT = sys.argv[4] if len(sys.argv) > 4 else "."
bad = []
def check(n, c, info=""):
    print(("PASS " if c else "FAIL ") + n, info)
    if not c: bad.append(n)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.getenv("CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"), args=["--no-sandbox"])
    pg = b.new_context(viewport={"width": 1280, "height": 1000}).new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    # cần server mới (run.sh xoá dữ liệu): tạo sẵn "Trần Bình" để thử ghép thư mục "Tran Binh" không dấu
    pg.request.post(URL + "/api/members", data={"member_id": "binh", "name": "Trần Bình"}, headers={"X-API-Token": TOKEN})
    pg.goto(URL + "/ui/"); pg.evaluate(f"localStorage.setItem('apiToken','{TOKEN}')"); pg.goto(URL + "/ui/#import"); pg.reload()
    pg.wait_for_selector("#iDir", state="attached"); time.sleep(1)
    pg.set_input_files("#iDir", ds); pg.wait_for_selector("#iPreview table"); time.sleep(1)
    prev = pg.inner_text("#iPreview"); pg.screenshot(path=f"{OUT}/import_preview.png")
    check("preview groups folders", "Nguyen Van An" in prev and "Tran Binh" in prev, prev[:160].replace("\n", " | "))
    check("existing member matched by accent-insensitive name", pg.locator("select[data-g]").nth(2).input_value() == "binh", pg.locator("select[data-g]").nth(2).input_value())
    check("HEIC flagged", "HEIC" in prev)
    check("no consent checkbox on import page", pg.locator("#iConsent").count() == 0)
    pg.click("#iGo")
    t0 = time.time()
    while time.time() - t0 < 120 and not pg.locator("#iGo").is_enabled(): time.sleep(1)
    time.sleep(1); res = pg.inner_text("#iResult"); pg.screenshot(path=f"{OUT}/import_result.png")
    check("import finished with results", "lưu" in res, res[:300].replace("\n", " | "))
    check("wrong-person image flagged", "giống người khác" in res)
    check("two-face image flagged", "2 mặt" in res)
    pg.goto(URL + "/ui/#members"); time.sleep(2)
    ml = pg.inner_text("#memberList"); check("members created/updated", "Nguyen Van An" in ml and "Trần Bình" in ml and "mẫu gốc" in ml, ml[:120].replace("\n", " "))
    check("empty folder did not create member", "Khong Mat" not in ml)
    check("no JS errors", not errs, errs[:3])
    b.close()
print("IMPORT E2E OK" if not bad else "IMPORT E2E FAILED: %s" % bad); sys.exit(1 if bad else 0)
