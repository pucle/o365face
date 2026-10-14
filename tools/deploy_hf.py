"""Tạo/cập nhật Hugging Face Space (Docker) và đẩy mã lên, bằng một lệnh.
    pip install huggingface_hub
    set HF_TOKEN=hf_xxx            (Git Bash: export HF_TOKEN=hf_xxx)   # token quyền write
    python tools/deploy_hf.py USER/club-attendance --api-token MAT_KHAU --hardware cpu-upgrade --storage small
    python tools/deploy_hf.py USER/club-attendance --api-token MAT_KHAU --dry-run      # chỉ in kế hoạch, không gọi mạng
Mặc định Space ở chế độ Private. Sau khi xong: python tools/smoke_test.py https://USER-club-attendance.hf.space --token MAT_KHAU --hf-token $HF_TOKEN
Lưu ý: bật storage/hardware trả phí tính tiền theo giờ; dừng bằng tools/space_power.py ... pause."""
import argparse, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGNORE = [".git*", "**/__pycache__/**", "data/**", "*.db", "tests/**", "docs/**", "deploy/**", ".venv/**", "*.zip", "client/**", "tools/**"]

ap = argparse.ArgumentParser()
ap.add_argument("repo", help="USER/TEN-SPACE"); ap.add_argument("--api-token", required=True, help="giá trị API_TOKEN của app (secret trên Space)")
ap.add_argument("--hardware", default="cpu-upgrade", help="cpu-basic (miễn phí, chậm) | cpu-upgrade | t4-small ...")
ap.add_argument("--storage", default="small", choices=["none", "small", "medium", "large"], help="Persistent storage (/data); none = mất dữ liệu khi khởi động lại")
ap.add_argument("--public", action="store_true"); ap.add_argument("--cors", default="", help="CORS_ORIGINS nếu UI ở domain khác (vd https://x.vercel.app)")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
files = [p for p in ("Dockerfile", "README.md", "requirements-server.txt", ".dockerignore", "common", "server") if os.path.exists(os.path.join(ROOT, p))]
print(f"Space: {a.repo} ({'public' if a.public else 'private'}), hardware={a.hardware}, storage={a.storage}\nSẽ đẩy: {files}\nSecrets/variables: API_TOKEN(secret), TZ_NAME=Asia/Ho_Chi_Minh" + (f", CORS_ORIGINS={a.cors}" if a.cors else ""))
if a.dry_run:
    sys.exit(0)
tok = os.getenv("HF_TOKEN") or sys.exit("Thiếu HF_TOKEN (token Hugging Face quyền write).")
from huggingface_hub import HfApi
api = HfApi(token=tok)
api.create_repo(a.repo, repo_type="space", space_sdk="docker", private=not a.public, exist_ok=True)
api.add_space_secret(a.repo, "API_TOKEN", a.api_token.strip())
api.add_space_variable(a.repo, "TZ_NAME", "Asia/Ho_Chi_Minh")
if a.cors: api.add_space_variable(a.repo, "CORS_ORIGINS", a.cors)
if a.storage != "none": api.request_space_storage(a.repo, storage=a.storage)
if a.hardware != "cpu-basic": api.request_space_hardware(a.repo, hardware=a.hardware)
import tempfile, shutil
with tempfile.TemporaryDirectory() as tmp:           # chỉ đẩy những gì Docker cần
    for p in files:
        s, d = os.path.join(ROOT, p), os.path.join(tmp, p)
        shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")) if os.path.isdir(s) else shutil.copy(s, d)
    api.upload_folder(folder_path=tmp, repo_id=a.repo, repo_type="space", commit_message="deploy")
print("Đã đẩy. Build mất ~5-10 phút (Dockerfile tải model). Theo dõi ở tab Logs của Space.")
print("URL:", "https://" + a.repo.replace("/", "-").replace("_", "-").lower() + ".hf.space")
