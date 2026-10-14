"""Chuyển dữ liệu giữa SQLite (club.db) và Postgres, hoặc sao lưu/khôi phục bằng tệp JSON.

    # SQLite cũ -> Postgres đám mây
    python tools/migrate_db.py --from-sqlite data/club.db --to-url "postgresql://..."
    # Postgres -> tệp JSON (sao lưu)            # tệp JSON -> Postgres/SQLite (khôi phục)
    python tools/migrate_db.py --from-url "postgresql://..." --to-json backup.json
    python tools/migrate_db.py --from-json backup.json --to-url "postgresql://..."
Mặc định KHÔNG ghi đè: nếu đích đã có dữ liệu thì dừng; thêm --replace để xoá đích rồi nạp lại.
"""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.storage import Storage  # noqa: E402


def open_src(a):
    if a.from_sqlite:
        d = os.path.dirname(os.path.abspath(a.from_sqlite))
        if os.path.basename(a.from_sqlite) != "club.db":
            sys.exit("Tệp SQLite phải tên club.db (thư mục chứa nó là DATA_DIR).")
        return Storage(d, "").export_all()
    if a.from_url:
        return Storage(tempfile.mkdtemp(), a.from_url).export_all()
    with open(a.from_json, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-sqlite"); ap.add_argument("--from-url"); ap.add_argument("--from-json")
    ap.add_argument("--to-url"); ap.add_argument("--to-json"); ap.add_argument("--to-sqlite-dir")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--no-embeddings", action="store_true",
                    help="bỏ vector khuôn mặt + mẫu người lạ (dùng khi đổi model, vd buffalo_l -> buffalo_s); giữ thành viên, ca trực, lịch sử, vắng mặt, cấu hình")
    a = ap.parse_args()
    if sum(map(bool, (a.from_sqlite, a.from_url, a.from_json))) != 1 or sum(map(bool, (a.to_url, a.to_json, a.to_sqlite_dir))) != 1:
        ap.error("chọn đúng một nguồn (--from-*) và một đích (--to-*)")
    data = open_src(a)
    if a.no_embeddings:
        for t in ("embeddings", "strangers"):
            data["tables"][t]["rows"] = []
        kv = data["tables"]["kv"]
        i = kv["cols"].index("key")
        kv["rows"] = [r for r in kv["rows"] if r[i] not in ("embedding_model", "presence")]
    n = {t: len(b["rows"]) for t, b in data["tables"].items()}
    print("Nguồn có:", n)
    if a.to_json:
        with open(a.to_json, "w", encoding="utf-8") as f:
            json.dump(data, f)
        print("Đã ghi", a.to_json, "(chứa vector khuôn mặt: giữ kín như dữ liệu cá nhân)")
        return
    dst = Storage(tempfile.mkdtemp(), a.to_url) if a.to_url else Storage(a.to_sqlite_dir, "")
    have = len(dst.members()) + len(dst.all_embeddings())
    if have and not a.replace:
        sys.exit(f"Đích đã có dữ liệu ({have} mục). Thêm --replace nếu chắc chắn muốn thay thế.")
    print("Đã nạp:", dst.import_all(data, replace=a.replace))


if __name__ == "__main__":
    main()
