"""Storage: SQLite thật, và luồng Postgres chạy với một module psycopg GIẢ (SQLite phía sau) để thử logic nối lại,
giao dịch, RETURNING, export/import. Cú pháp SQL Postgres thật được kiểm ở tests/pg_sql_check.py."""
import contextlib
import re
import sqlite3
import sys
import tempfile
import types
import unittest

import numpy as np

import _path  # noqa: F401
from server import storage as st


class FakeOpErr(Exception):
    pass


class FakeIfErr(Exception):
    pass


class FakeCur:
    def __init__(self, cur):
        self.c = cur
        self.rowcount = cur.rowcount

    def fetchone(self):
        return self.c.fetchone()

    def fetchall(self):
        return self.c.fetchall()

    def executemany(self, q, rows):
        self.c.executemany(q.replace("%s", "?"), rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, shared):
        self.sh, self.closed = shared, False
        self.db = shared["db"]

    def _q(self, sql):
        q = sql.replace("%s", "?")
        if q.lstrip().upper().startswith("CREATE TABLE"):
            q = q.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT").replace("BYTEA", "BLOB").replace("DOUBLE PRECISION", "REAL")
        return q

    def execute(self, sql, args=()):
        if self.sh.get("drop_next"):
            self.sh["drop_next"] = False
            raise FakeOpErr("server closed the connection")
        self.sh["sql"].append(sql)
        if "setval" in sql:
            return FakeCur(self.db.execute("SELECT 1 WHERE 0"))
        return FakeCur(self.db.execute(self._q(sql), tuple(args)))

    def cursor(self):
        return FakeCur(self.db.cursor())

    @contextlib.contextmanager
    def transaction(self):
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def close(self):
        self.closed = True


def install_fake():
    shared = {"db": sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None), "sql": [], "connects": 0}
    mod = types.ModuleType("psycopg")
    mod.OperationalError, mod.InterfaceError = FakeOpErr, FakeIfErr

    def connect(url, **kw):
        shared["connects"] += 1
        shared["url"] = url
        return FakeConn(shared)
    mod.connect = connect
    sys.modules["psycopg"] = mod
    return shared


class PgPathTests(unittest.TestCase):
    def setUp(self):
        self.sh = install_fake()
        self.s = st.Storage(tempfile.mkdtemp(), "postgres://u:p@host/db?sslmode=require")

    def tearDown(self):
        sys.modules.pop("psycopg", None)

    def test_kind_and_url(self):
        self.assertEqual(self.s.kind, "postgres")
        self.assertTrue(self.sh["url"].startswith("postgresql://"))
        self.assertTrue(self.s.ping())

    def test_returning_and_crud(self):
        sid = self.s.add_shift("m", "2026-01-01T08:00:00", "2026-01-01T10:00:00")
        self.assertIsInstance(sid, int)
        self.assertEqual(self.s.get_shift(sid)[1], "m")
        self.assertTrue(any(q.endswith("RETURNING id") for q in self.sh["sql"]))
        self.assertTrue(any('"end"' in q for q in self.sh["sql"]))

    def test_reconnect_once(self):
        self.s.kv_set("a", 1)
        n = self.sh["connects"]
        self.sh["drop_next"] = True          # kết nối bị cắt giữa chừng (Neon scale-to-zero)
        self.assertEqual(self.s.kv_get("a"), 1)
        self.assertEqual(self.sh["connects"], n + 1)

    def test_export_import_roundtrip_to_sqlite(self):
        v = np.arange(512, dtype="float32")
        self.s.upsert_member("m1", "An", "t")
        self.s.add_embedding("m1", v, "door", 1.0, 2.0, "t", "i", "front")
        self.s.add_event("2026-01-01T08:00:00", "alert_unknown_door", None, "x")
        self.s.add_shift("m1", "2026-01-01T08:00:00", "2026-01-01T10:00:00")
        data = self.s.export_all()
        t = st.Storage(tempfile.mkdtemp())      # SQLite
        # (env DATABASE_URL không đặt) -> SQLite
        t.import_all(data, replace=True)
        rows = t.all_embeddings()
        self.assertEqual(len(rows), 1)
        np.testing.assert_array_equal(rows[0]["vec"], v)
        self.assertEqual(t.events_filtered(["alert_unknown_door"])[0][3], "x")
        self.assertEqual(len(t.all_shifts()), 1)


class SqliteTests(unittest.TestCase):
    def setUp(self):
        self.s = st.Storage(tempfile.mkdtemp(), "")

    def test_events_filtered(self):
        for i, k in enumerate(["checkin", "alert_unknown_door", "away", "checkout"]):
            self.s.add_event(f"2026-01-0{i + 1}T08:00:00", k, "m" if k != "alert_unknown_door" else None, "")
        self.assertEqual([e[1] for e in self.s.events_filtered(["alert_unknown_door", "away"])], ["away", "alert_unknown_door"])
        self.assertEqual(len(self.s.events_filtered(None, 2)), 2)
        self.assertEqual(len(self.s.events_filtered(None, 10, "2026-01-02", "2026-01-04")), 2)
        self.assertEqual(len(self.s.events_filtered(None, 10, member_id="m")), 3)

    def test_import_rejects_garbage(self):
        with self.assertRaises(ValueError):
            self.s.import_all({"version": 9})

    def test_count_strangers(self):
        self.assertEqual(self.s.count_strangers(), 0)
        self.s.add_stranger(np.zeros(512, "float32"), 0, 0, "room", "t")
        self.assertEqual(self.s.count_strangers(), 1)
        self.assertEqual(self.s.clear_strangers(), 1)


class TranslateTests(unittest.TestCase):
    def test_translate(self):
        self.assertEqual(st.pg_translate("SELECT 1 FROM shifts WHERE end<=?"), 'SELECT 1 FROM shifts WHERE "end"<=%s')
        self.assertTrue(st.pg_translate("INSERT INTO events(ts,kind) VALUES(?,?)").endswith("RETURNING id"))
        self.assertFalse(st.pg_translate("INSERT INTO kv(key,value) VALUES(?,?)").endswith("RETURNING id"))
        self.assertNotIn("RETURNING", st.pg_translate("INSERT INTO members(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name"))

    def test_open_backend_strips_quotes(self):
        install_fake()
        try:
            b = st.open_backend(tempfile.mkdtemp(), ' "postgres://u:p@h/d" ')
            self.assertEqual(b.kind, "postgres")
        finally:
            sys.modules.pop("psycopg", None)


if __name__ == "__main__":
    unittest.main()
