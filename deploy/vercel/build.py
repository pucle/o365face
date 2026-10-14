"""Chuẩn bị thư mục deploy/vercel cho Vercel: chép UI vào public/ (+ config.js tuỳ chọn).
    python deploy/vercel/build.py [--api-base https://backend]    # bỏ --api-base khi dùng proxy /api (khuyến nghị)
Rồi:  cd deploy/vercel && npx vercel --prod   (đặt BACKEND_URL, tuỳ chọn HF_TOKEN trong Project Settings → Environment Variables)"""
import argparse, os, shutil

here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("--api-base", default="")
a = ap.parse_args()
src, dst = os.path.join(here, "..", "..", "server", "static"), os.path.join(here, "public")
shutil.rmtree(dst, ignore_errors=True); shutil.copytree(src, dst)
with open(os.path.join(dst, "config.js"), "w", encoding="utf-8") as f:
    f.write('window.APP_CONFIG = { apiBase: %r };\n' % a.api_base.rstrip("/"))
print("Đã tạo", dst, "| apiBase =", repr(a.api_base) or "(cùng origin, qua proxy /api)")
