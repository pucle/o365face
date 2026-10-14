"""Tắt/bật Hugging Face Space theo giờ để khỏi tính tiền ngoài giờ (Space phần cứng trả phí tính theo giờ chạy).
    pip install huggingface_hub
    set HF_TOKEN=hf_xxx (token có quyền write)
    python tools/space_power.py USER/SPACE pause|restart|status
Lên lịch: Task Scheduler (Windows) hoặc cron: restart lúc 7:55, pause lúc 20:05."""
import os, sys
from huggingface_hub import HfApi

if len(sys.argv) != 3 or sys.argv[2] not in ("pause", "restart", "status"):
    sys.exit(__doc__)
api, repo = HfApi(token=os.environ["HF_TOKEN"]), sys.argv[1]
if sys.argv[2] == "pause": api.pause_space(repo)
elif sys.argv[2] == "restart": api.restart_space(repo)
rt = api.get_space_runtime(repo)
print(repo, rt.stage, rt.hardware)
