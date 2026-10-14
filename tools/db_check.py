"""Kiểm tra kết nối database đám mây (Neon/Supabase) TRƯỚC khi deploy.

    PowerShell:  $env:DATABASE_URL="postgresql://...";  python tools/db_check.py
    cmd:         set "DATABASE_URL=postgresql://..."  &&  python tools/db_check.py
    Git Bash:    DATABASE_URL='postgresql://...' python tools/db_check.py

Tạo bảng nếu chưa có, ghi - đọc - xoá một dòng thử, đếm dữ liệu hiện có. Không in mật khẩu.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("Chưa đặt DATABASE_URL (xem docs/11-huong-dan-deploy-chi-tiet.md).")
    from server.storage import Storage
    t0 = time.time()
    try:
        s = Storage(tempfile.mkdtemp(), url)
    except Exception as e:
        sys.exit(f"KHÔNG kết nối được: {e}")
    print(f"Kết nối + tạo bảng: {time.time() - t0:.1f} s (lần đầu có thể chậm nếu Neon đang ngủ)")
    s.kv_set("_db_check", {"t": time.time()})
    assert s.kv_get("_db_check"), "ghi rồi nhưng đọc không thấy"
    s.execute("DELETE FROM kv WHERE key=?", ("_db_check",))
    print("Ghi / đọc / xoá thử: OK")
    print("Đang có:", len(s.members()), "thành viên,", len(s.all_embeddings()), "mẫu mặt,", s.count_strangers(), "mẫu người lạ,",
          len(s.recent_events(10**6)), "sự kiện")


if __name__ == "__main__":
    main()
