"""Lưu trữ dữ liệu: SQLite (mặc định, tệp cục bộ) hoặc Postgres trên cloud (đặt biến DATABASE_URL).

Cùng một lớp `Storage` cho cả hai: câu lệnh SQL viết theo dạng dùng chung (dấu `?`), backend Postgres tự đổi
`?` -> `%s`, thêm `RETURNING id`, dùng kiểu BYTEA/BIGSERIAL. Postgres cần thư viện `psycopg[binary]` (có trong requirements-server.txt).
Gợi ý nhà cung cấp miễn phí: Neon hoặc Supabase (xem docs/11). Dữ liệu là vector đặc trưng (2 KB/mẫu) + lịch sử nên rất nhỏ.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Iterable, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------------------------- lược đồ
SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT);
CREATE TABLE IF NOT EXISTS embeddings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, member_id TEXT NOT NULL,
  vec BLOB NOT NULL, source TEXT, pitch REAL, yaw REAL, created TEXT, img TEXT, step TEXT);
CREATE TABLE IF NOT EXISTS strangers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, vec BLOB NOT NULL, pitch REAL, yaw REAL, context TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS shifts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, member_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, member_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS absences(
  id INTEGER PRIMARY KEY AUTOINCREMENT, member_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, minutes REAL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_emb_member ON embeddings(member_id);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT);
CREATE TABLE IF NOT EXISTS embeddings(
  id BIGSERIAL PRIMARY KEY, member_id TEXT NOT NULL,
  vec BYTEA NOT NULL, source TEXT, pitch DOUBLE PRECISION, yaw DOUBLE PRECISION, created TEXT, img TEXT, step TEXT);
CREATE TABLE IF NOT EXISTS strangers(
  id BIGSERIAL PRIMARY KEY, vec BYTEA NOT NULL, pitch DOUBLE PRECISION, yaw DOUBLE PRECISION, context TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS shifts(
  id BIGSERIAL PRIMARY KEY, member_id TEXT NOT NULL, start TEXT NOT NULL, "end" TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id BIGSERIAL PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, member_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS absences(
  id BIGSERIAL PRIMARY KEY, member_id TEXT NOT NULL, start TEXT NOT NULL, "end" TEXT NOT NULL, minutes DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_emb_member ON embeddings(member_id);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
"""

# cột thêm sau này (chỉ cần cho tệp SQLite của bản đầu tiên)
MIGRATIONS = [("members", "created", "TEXT"), ("embeddings", "img", "TEXT"), ("embeddings", "step", "TEXT")]
SERIAL_TABLES = ("embeddings", "strangers", "shifts", "events", "absences")
TABLES = ("members", "embeddings", "strangers", "shifts", "events", "absences", "kv")
# `end` là từ khoá của SQL chuẩn: Postgres bắt buộc đặt trong ngoặc kép; SQLite chấp nhận cả hai dạng.
PG_RESERVED = (("shifts", "end"), ("absences", "end"))


def pg_translate(sql: str) -> str:
    """Đổi câu lệnh dạng dùng chung sang Postgres: `?` -> `%s`, cột `end` -> "end", thêm RETURNING id cho INSERT bảng có id."""
    out = sql.replace("?", "%s")
    # Không câu SQL nào của Storage dùng CASE...END hay chuỗi chứa chữ "end", nên đặt ngoặc kép cho mọi từ `end` đứng riêng là an toàn.
    out = re.sub(r'(?<!["\w])end(?![\w"])', '"end"', out)
    head = out.lstrip().upper()
    if head.startswith("INSERT INTO"):
        table = out.split()[2].split("(")[0]
        if table in SERIAL_TABLES and "RETURNING" not in head:
            out += " RETURNING id"
    return out


# ---------------------------------------------------------------------------------------------- backend SQLite
class _Sqlite:
    kind = "sqlite"

    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "club.db")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA_SQLITE)
            for table, col, typ in MIGRATIONS:
                cols = [r[1] for r in self.db.execute(f"PRAGMA table_info({table})")]
                if col not in cols:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            self.db.commit()

    def execute(self, sql: str, args: Iterable = ()) -> Tuple[Optional[int], int]:
        """Trả về (id dòng vừa thêm, số dòng bị ảnh hưởng)."""
        with self.lock:
            cur = self.db.execute(sql, tuple(args))
            self.db.commit()
            return cur.lastrowid, cur.rowcount

    def query(self, sql: str, args: Iterable = ()) -> List[tuple]:
        with self.lock:
            return list(self.db.execute(sql, tuple(args)))

    def many(self, sql: str, rows: List[tuple]) -> None:
        with self.lock:
            self.db.executemany(sql, rows)
            self.db.commit()

    def tx(self, stmts: List[Tuple[str, tuple]]) -> List[int]:
        with self.lock:
            counts = []
            try:
                for sql, args in stmts:
                    counts.append(self.db.execute(sql, tuple(args)).rowcount)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return counts

    def backup_to(self, dest_path: str) -> None:
        with self.lock:
            dest = sqlite3.connect(dest_path)
            self.db.backup(dest)
            dest.close()


# ---------------------------------------------------------------------------------------------- backend Postgres
class _Postgres:
    kind = "postgres"

    def __init__(self, url: str, retries: int = 3):
        try:
            import psycopg  # noqa: F401
        except ImportError as e:                       # pragma: no cover - phụ thuộc môi trường
            raise RuntimeError("DATABASE_URL được đặt nhưng thiếu thư viện: pip install \"psycopg[binary]\"") from e
        self._psycopg = __import__("psycopg")
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        self.url, self.retries = url, retries
        self.lock = threading.RLock()
        self.conn = None
        self._connect()
        with self.lock:
            for stmt in [s.strip() for s in SCHEMA_PG.split(";") if s.strip()]:
                self._run(lambda c, s=stmt: c.execute(s))

    def _connect(self):
        last = None
        for i in range(self.retries):
            try:
                self.conn = self._psycopg.connect(self.url, autocommit=True, connect_timeout=15)
                return
            except Exception as e:                      # Neon/Supabase có thể đang "thức dậy": thử lại vài lần
                last = e
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"Không kết nối được database ({type(last).__name__}). Kiểm tra DATABASE_URL, mật khẩu, sslmode=require.") from last

    def _run(self, fn):
        """Chạy fn(conn); nếu kết nối đã bị cắt (scale-to-zero, idle timeout) thì nối lại và thử một lần nữa."""
        bad = (self._psycopg.OperationalError, self._psycopg.InterfaceError)
        try:
            return fn(self.conn)
        except bad:
            try:
                self.conn.close()
            except Exception:
                pass
            self._connect()
            return fn(self.conn)

    def execute(self, sql: str, args: Iterable = ()) -> Tuple[Optional[int], int]:
        q = pg_translate(sql)
        with self.lock:
            def go(c):
                cur = c.execute(q, tuple(args))
                rid = cur.fetchone()[0] if q.endswith("RETURNING id") else None
                return rid, cur.rowcount
            return self._run(go)

    def query(self, sql: str, args: Iterable = ()) -> List[tuple]:
        q = pg_translate(sql)
        with self.lock:
            return self._run(lambda c: c.execute(q, tuple(args)).fetchall())

    def many(self, sql: str, rows: List[tuple]) -> None:
        q = pg_translate(sql)
        with self.lock:
            def go(c):
                with c.transaction():
                    with c.cursor() as cur:
                        cur.executemany(q, rows)
            self._run(go)

    def tx(self, stmts: List[Tuple[str, tuple]]) -> List[int]:
        with self.lock:
            def go(c):
                counts = []
                with c.transaction():
                    for sql, args in stmts:
                        counts.append(c.execute(pg_translate(sql), tuple(args)).rowcount)
                return counts
            return self._run(go)

    def backup_to(self, dest_path: str) -> None:
        raise NotImplementedError("Postgres: dùng /api/export (JSON) hoặc công cụ của nhà cung cấp (pg_dump)")


def open_backend(data_dir: str, database_url: Optional[str] = None):
    url = database_url if database_url is not None else os.getenv("DATABASE_URL", "")
    url = (url or "").strip().strip("\"'").strip()
    return _Postgres(url) if url else _Sqlite(data_dir)


# ---------------------------------------------------------------------------------------------- Storage
class Storage:
    def __init__(self, data_dir: str, database_url: Optional[str] = None):
        self.b = open_backend(data_dir, database_url)
        self.kind = self.b.kind
        self.path = getattr(self.b, "path", None)

    # ---- tiện ích -----------------------------------------------------
    def execute(self, sql: str, args: Iterable = ()) -> int:
        return self.b.execute(sql, args)[0]

    def query(self, sql: str, args: Iterable = ()) -> List[tuple]:
        return self.b.query(sql, args)

    def ping(self) -> bool:
        try:
            return self.b.query("SELECT 1") == [(1,)]
        except Exception:
            return False

    # ---- kv / cấu hình ------------------------------------------------
    def kv_get(self, key: str, default: Any = None) -> Any:
        r = self.query("SELECT value FROM kv WHERE key=?", (key,))
        if not r:
            return default
        try:
            return json.loads(r[0][0])
        except (ValueError, TypeError):
            return default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value)))

    # ---- thành viên ---------------------------------------------------
    def upsert_member(self, member_id: str, name: str, created: str) -> None:
        self.execute("INSERT INTO members(id,name,created) VALUES(?,?,?) "
                     "ON CONFLICT(id) DO UPDATE SET name=excluded.name", (member_id, name, created))

    def members(self) -> List[Tuple[str, str]]:
        return [(r[0], r[1]) for r in self.query("SELECT id,name FROM members ORDER BY lower(name)")]

    def member_name(self, member_id: Optional[str]) -> str:
        if not member_id:
            return ""
        r = self.query("SELECT name FROM members WHERE id=?", (member_id,))
        return r[0][0] if r else member_id

    def member_exists(self, member_id: str) -> bool:
        return bool(self.query("SELECT 1 FROM members WHERE id=?", (member_id,)))

    def delete_member(self, member_id: str, keep_shifts: bool = False) -> None:
        stmts = [("DELETE FROM embeddings WHERE member_id=?", (member_id,)), ("DELETE FROM members WHERE id=?", (member_id,))]
        if not keep_shifts:
            stmts.append(("DELETE FROM shifts WHERE member_id=?", (member_id,)))
        self.b.tx(stmts)

    # ---- embedding ----------------------------------------------------
    def add_embedding(self, member_id: str, vec: np.ndarray, source: str, pitch, yaw,
                      created: str, img: str, step: str = "") -> None:
        self.execute("INSERT INTO embeddings(member_id,vec,source,pitch,yaw,created,img,step) VALUES(?,?,?,?,?,?,?,?)",
                     (member_id, np.asarray(vec, dtype=np.float32).tobytes(), source, _f(pitch), _f(yaw), created, img, step))

    def add_embeddings_bulk(self, rows: List[tuple]) -> None:
        """rows: (member_id, vec, source, pitch, yaw, created, img, step). Ghi một lần trong một giao dịch."""
        data = [(m, np.asarray(v, dtype=np.float32).tobytes(), src, _f(p), _f(y), c, i, st) for m, v, src, p, y, c, i, st in rows]
        self.b.many("INSERT INTO embeddings(member_id,vec,source,pitch,yaw,created,img,step) VALUES(?,?,?,?,?,?,?,?)", data)

    def delete_embeddings_by_img(self, member_id: str, imgs: Iterable[str]) -> int:
        imgs = list(imgs)
        if not imgs:
            return 0
        q = ",".join("?" * len(imgs))
        return self.b.execute(f"DELETE FROM embeddings WHERE member_id=? AND img IN ({q})", [member_id, *imgs])[1]

    def all_embeddings(self) -> List[dict]:
        rows = self.query("SELECT member_id,vec,source,pitch,yaw,img,id,step,created FROM embeddings ORDER BY id")
        return [{"member_id": m, "vec": np.frombuffer(bytes(b), dtype=np.float32).copy(), "source": s, "pitch": p,
                 "yaw": y, "img": (i if i else f"legacy-{k}"), "id": k, "step": st, "created": c}
                for m, b, s, p, y, i, k, st, c in rows]

    def delete_embeddings(self, member_id: str, source: Optional[str] = None) -> int:
        if source:
            return self.b.execute("DELETE FROM embeddings WHERE member_id=? AND source=?", (member_id, source))[1]
        return self.b.execute("DELETE FROM embeddings WHERE member_id=?", (member_id,))[1]

    # ---- mẫu người lạ -------------------------------------------------
    def add_stranger(self, vec: np.ndarray, pitch, yaw, context: str, created: str) -> None:
        self.execute("INSERT INTO strangers(vec,pitch,yaw,context,created) VALUES(?,?,?,?,?)",
                     (np.asarray(vec, dtype=np.float32).tobytes(), _f(pitch), _f(yaw), context, created))

    def strangers(self) -> np.ndarray:
        rows = self.query("SELECT vec FROM strangers ORDER BY id")
        if not rows:
            return np.zeros((0, 512), dtype=np.float32)
        return np.stack([np.frombuffer(bytes(r[0]), dtype=np.float32) for r in rows])

    def count_strangers(self) -> int:
        return int(self.query("SELECT COUNT(*) FROM strangers")[0][0])

    def clear_strangers(self) -> int:
        return self.b.execute("DELETE FROM strangers")[1]

    # ---- ca trực ------------------------------------------------------
    def add_shift(self, member_id: str, start: str, end: str) -> int:
        return self.execute("INSERT INTO shifts(member_id,start,end) VALUES(?,?,?)", (member_id, start, end))

    def get_shift(self, shift_id: int) -> Optional[tuple]:
        r = self.query("SELECT id,member_id,start,end FROM shifts WHERE id=?", (shift_id,))
        return r[0] if r else None

    def delete_shift(self, shift_id: int) -> None:
        self.execute("DELETE FROM shifts WHERE id=?", (shift_id,))

    def shifts_between(self, lo: str, hi: str) -> List[tuple]:
        return self.query("SELECT id,member_id,start,end FROM shifts WHERE start>=? AND start<? ORDER BY start", (lo, hi))

    def all_shifts(self) -> List[tuple]:
        return self.query("SELECT id,member_id,start,end FROM shifts")

    # ---- sự kiện / cảnh báo / vắng mặt --------------------------------
    def add_event(self, ts: str, kind: str, member_id: Optional[str], detail: str = "") -> None:
        self.execute("INSERT INTO events(ts,kind,member_id,detail) VALUES(?,?,?,?)", (ts, kind, member_id, detail))

    def events_between(self, lo: str, hi: str) -> List[tuple]:
        return self.query("SELECT ts,kind,member_id,detail FROM events WHERE ts>=? AND ts<? ORDER BY ts", (lo, hi))

    def prune_events(self, before_ts: str) -> int:
        """Xoá lịch sử cũ hơn mốc (giữ DB đám mây nhỏ). Trả về số dòng đã xoá."""
        return self.b.execute("DELETE FROM events WHERE ts<?", (before_ts,))[1]

    def recent_events(self, n: int = 30) -> List[tuple]:
        return self.query("SELECT ts,kind,member_id,detail FROM events ORDER BY id DESC LIMIT ?", (n,))

    def events_filtered(self, kinds: Optional[List[str]] = None, limit: int = 100, lo: Optional[str] = None,
                        hi: Optional[str] = None, member_id: Optional[str] = None) -> List[tuple]:
        """Lịch sử mới nhất trước. kinds=None: mọi loại."""
        where, args = [], []
        if kinds:
            where.append("kind IN (%s)" % ",".join("?" * len(kinds))); args += list(kinds)
        if lo:
            where.append("ts>=?"); args.append(lo)
        if hi:
            where.append("ts<?"); args.append(hi)
        if member_id:
            where.append("member_id=?"); args.append(member_id)
        sql = "SELECT ts,kind,member_id,detail FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        return self.query(sql, args + [int(limit)])

    def add_absence(self, member_id: str, start: str, end: str, minutes: float) -> None:
        self.execute("INSERT INTO absences(member_id,start,end,minutes) VALUES(?,?,?,?)", (member_id, start, end, _f(minutes)))

    def absences_for(self, member_id: str, lo: str, hi: str) -> List[tuple]:
        return self.query("SELECT start,end,minutes FROM absences WHERE member_id=? AND start>=? AND end<=? ORDER BY start",
                          (member_id, lo, hi))

    # ---- sao lưu / chuyển dữ liệu --------------------------------------
    def backup_to(self, dest_path: str) -> None:
        self.b.backup_to(dest_path)

    def export_all(self) -> dict:
        """Toàn bộ dữ liệu dạng JSON (vector mã hoá base64). Dùng để sao lưu/chuyển giữa SQLite và Postgres."""
        out: dict = {"version": 1, "kind": self.kind, "tables": {}}
        for t in TABLES:
            cols = TABLE_COLS[t]
            sel = ",".join(f'"{c}"' if c == "end" and self.kind == "postgres" else c for c in cols)
            rows = self.b.query(f"SELECT {sel} FROM {t}" + (" ORDER BY id" if t in SERIAL_TABLES else ""))
            conv = []
            for r in rows:
                conv.append([base64.b64encode(bytes(v)).decode("ascii") if c == "vec" else v for c, v in zip(cols, r)])
            out["tables"][t] = {"cols": list(cols), "rows": conv}
        return out

    def import_all(self, data: dict, replace: bool = False) -> dict:
        """Nạp dữ liệu từ export_all(). replace=True: xoá dữ liệu hiện có trước (trong cùng một giao dịch)."""
        if data.get("version") != 1 or "tables" not in data:
            raise ValueError("Tệp không phải bản sao lưu hợp lệ.")
        stmts: List[Tuple[str, tuple]] = []
        counts = {}
        if replace:
            stmts += [(f"DELETE FROM {t}", ()) for t in reversed(TABLES)]
        for t in TABLES:
            blk = data["tables"].get(t)
            if not blk:
                continue
            cols = blk["cols"]
            if set(cols) - set(TABLE_COLS[t]):
                raise ValueError(f"Bảng {t} có cột lạ.")
            ins = ",".join(f'"{c}"' if c == "end" and self.kind == "postgres" else c for c in cols)
            sql = f"INSERT INTO {t}({ins}) VALUES({','.join('?' * len(cols))})"
            if t == "members":
                sql += " ON CONFLICT(id) DO UPDATE SET name=excluded.name"
            if t == "kv":
                sql += " ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            n = 0
            for row in blk["rows"]:
                vals = tuple(base64.b64decode(v) if c == "vec" else v for c, v in zip(cols, row))
                stmts.append((sql, vals)); n += 1
            counts[t] = n
        self.b.tx(stmts)
        if self.kind == "postgres":      # id đã được nạp tường minh -> đẩy bộ đếm tự tăng lên sau id lớn nhất, nếu không INSERT sau đó sẽ trùng id
            for t in SERIAL_TABLES:
                self.b.query(f"SELECT setval(pg_get_serial_sequence('{t}','id'), "
                             f"COALESCE((SELECT MAX(id) FROM {t}),1), (SELECT COUNT(*)>0 FROM {t}))")
        return counts


TABLE_COLS = {
    "members": ("id", "name", "created"),
    "embeddings": ("id", "member_id", "vec", "source", "pitch", "yaw", "created", "img", "step"),
    "strangers": ("id", "vec", "pitch", "yaw", "context", "created"),
    "shifts": ("id", "member_id", "start", "end"),
    "events": ("id", "ts", "kind", "member_id", "detail"),
    "absences": ("id", "member_id", "start", "end", "minutes"),
    "kv": ("key", "value"),
}


def _f(v):
    return None if v is None else float(v)
