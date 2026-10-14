"""Kiểm tra mọi câu SQL của Storage trên một Postgres THẬT (chỉ cần psql + một database trống để thử).

Cách làm: chạy một kịch bản dùng đủ các hàm của Storage trên SQLite, ghi lại từng câu SQL, đổi sang dạng Postgres
bằng pg_translate rồi `PREPARE` trên Postgres (kiểm tra cú pháp, tên bảng/cột, kiểu). Không thay thế việc thử với psycopg
và máy chủ thật (Neon/Supabase), nhưng bắt được lỗi cú pháp/tên cột.

    PGCHECK_CMD="psql -X -q -v ON_ERROR_STOP=1 -d clubtest" python tests/pg_sql_check.py
(PGCHECK_CMD mặc định như trên; nếu cần user khác: PGCHECK_CMD="su postgres -c 'psql -d clubtest'" không hỗ trợ -f, nên dùng PGUSER/PGHOST.)
"""
import os
import re
import shlex
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import storage as st  # noqa: E402

seen = []


def rec(sql):
    if sql not in seen:
        seen.append(sql)


class Rec(st._Sqlite):
    def execute(self, sql, args=()):
        rec(sql); return super().execute(sql, args)

    def query(self, sql, args=()):
        rec(sql); return super().query(sql, args)

    def many(self, sql, rows):
        rec(sql); return super().many(sql, rows)

    def tx(self, stmts):
        for s, _ in stmts:
            rec(s)
        return super().tx(stmts)


def workload():
    d = tempfile.mkdtemp()
    orig = st.open_backend
    st.open_backend = lambda data_dir, url=None: Rec(data_dir)
    try:
        s = st.Storage(d)
    finally:
        st.open_backend = orig
    v = np.random.RandomState(0).randn(512).astype("float32")
    s.kv_set("a", {"x": 1}); s.kv_get("a")
    s.upsert_member("m1", "An", "2026-01-01"); s.members(); s.member_name("m1"); s.member_exists("m1")
    s.add_embedding("m1", v, "door", 1.0, 2.0, "t", "img1", "front")
    s.add_embeddings_bulk([("m1", v, "door", 1.0, 2.0, "t", "img2", "left")])
    s.all_embeddings(); s.delete_embeddings_by_img("m1", ["img2"]); s.delete_embeddings("m1", "door"); s.delete_embeddings("m1")
    s.add_stranger(v, 0.0, 0.0, "room", "t"); s.strangers(); s.count_strangers(); s.clear_strangers()
    sid = s.add_shift("m1", "2026-01-01T08:00:00", "2026-01-01T10:00:00")
    s.get_shift(sid); s.shifts_between("a", "z"); s.all_shifts(); s.delete_shift(sid)
    s.add_event("2026-01-01T08:00:00", "checkin", "m1", "d"); s.events_between("a", "z"); s.recent_events(5)
    s.events_filtered(["checkin", "away"], 10, "a", "z", "m1"); s.events_filtered()
    s.add_absence("m1", "a", "b", 3.0); s.absences_for("m1", "a", "z")
    s.ping()
    data = s.export_all()
    s.import_all(data, replace=True)
    s.delete_member("m1"); s.delete_member("m1", keep_shifts=True)


def to_prepared(sql, i):
    q = st.pg_translate(sql)
    n = [0]

    def sub(_):
        n[0] += 1
        return f"${n[0]}"
    q = re.sub(r"%s", sub, q)
    return f"PREPARE s{i} AS {q};\nDEALLOCATE s{i};\n"


def main():
    workload()
    # import_all/export_all sinh câu lệnh theo kind: dựng lại dạng Postgres để kiểm tra riêng
    extra = []
    for t, cols in st.TABLE_COLS.items():
        ins = ",".join(f'"{c}"' if c == "end" else c for c in cols)
        sql = f"INSERT INTO {t}({ins}) VALUES({','.join('?' * len(cols))})"
        if t == "members":
            sql += " ON CONFLICT(id) DO UPDATE SET name=excluded.name"
        if t == "kv":
            sql += " ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        extra.append(sql)
        sel = ",".join(f'"{c}"' if c == "end" else c for c in cols)
        extra.append(f"SELECT {sel} FROM {t}" + (" ORDER BY id" if t in st.SERIAL_TABLES else ""))
    stmts = list(seen) + extra
    script = ["DROP SCHEMA IF EXISTS chk CASCADE;", "CREATE SCHEMA chk;", "SET search_path=chk;", st.SCHEMA_PG]
    script += [to_prepared(s, i) for i, s in enumerate(stmts)]
    script.append("SELECT setval(pg_get_serial_sequence('events','id'), COALESCE((SELECT MAX(id) FROM events),1), (SELECT COUNT(*)>0 FROM events));")
    script.append("DROP SCHEMA chk CASCADE;")
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as f:
        f.write("\n".join(script)); path = f.name
    cmd = shlex.split(os.getenv("PGCHECK_CMD", "psql -X -q -v ON_ERROR_STOP=1")) + ["-f", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"{len(stmts)} câu SQL kiểm tra trên Postgres")
    if r.returncode:
        print(r.stderr); sys.exit(1)
    print("OK: Postgres chấp nhận mọi câu lệnh (PREPARE).")


if __name__ == "__main__":
    main()
