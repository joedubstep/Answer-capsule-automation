"""The Notion SQL tool returns at most 100 rows a call, whatever the LIMIT. Every query the Time Ledger builds must
have a stable ORDER BY and be read in pages of 100 (OFFSET 0, 100, 200 ...) until a page comes back short."""
import datetime as dt
import io
import json
import random
import re
import sqlite3
import unittest
from contextlib import redirect_stdout

from tools.time_ledger import common as C
from tools.time_ledger import run
from tools.time_ledger.tests.base import TempWork, page_fetch_json

DS = "collection://00000000-0000-0000-0000-000000000000"


def call(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run.main(list(args))
    return code, buf.getvalue()


def sql_line(out, prefix="SQL: "):
    return next(line for line in out.splitlines() if line.startswith(prefix)).split(prefix, 1)[1]


def builders():
    ws, we = dt.date(2026, 10, 26), dt.date(2026, 11, 1)
    return {"existing": run.existing_sql(DS, "2026-11-01", "2026-11-02"), "existing_all": run.existing_sql(DS),
            "week_this": run.week_this_sql(DS, ws, we), "week_prev": run.week_prev_sql(DS, ws, we)}


def fake_db(n):
    """An in-memory SQLite table shaped like the 15-Min Action Log (Notion's SQL mode is SQLite)."""
    db = sqlite3.connect(":memory:")
    db.execute('CREATE TABLE "%s" ("Key" TEXT, "date:Date:start" TEXT, "Block start" TEXT, "Action" TEXT, '
               '"url" TEXT, "Minutes (est)" REAL, "Role" TEXT, "Task" TEXT, "Kind" TEXT, "AI" TEXT, "Source" TEXT)'
               % DS)
    rnd = random.Random(7)
    rows = []
    for i in range(n):
        day = "2026-10-%02d" % (26 + i % 6)
        # many rows share a Key prefix, a date and a block: only the url makes the order total
        rows.append(("k%03d" % (i % 40), day, "8:00 am", "Sample action %d" % i,
                     "https://www.notion.so/%032x" % rnd.getrandbits(128), 15.0, ["Sales", "Admin"][i % 2], "",
                     ["Outreach", "Admin", "Tools"][i % 3], "__NO__", "log"))
    rnd.shuffle(rows)
    db.executemany('INSERT INTO "%s" VALUES (?,?,?,?,?,?,?,?,?,?,?)' % DS, rows)
    return db


def read_all(db, base):
    """Page the way the skill does: OFFSET 0, 100, 200 ... until a page has fewer than 100 rows."""
    got, offsets, off = [], [], 0
    while True:
        offsets.append(off)
        page = db.execute(run.paged(base, off)).fetchall()
        got += page
        if len(page) < run.PAGE:
            return got, offsets
        off += run.PAGE


class SqlBuilderTests(unittest.TestCase):
    def test_every_query_has_a_stable_order_and_pages_of_100(self):
        for name, q in builders().items():
            self.assertNotIn("LIMIT", q, name)                       # the page is added by paged()
            self.assertRegex(q, r'ORDER BY .+$', name)
            self.assertTrue(q.endswith('"url"') or q.endswith("ORDER BY 1, 2, 3"), name)
            self.assertTrue(run.paged(q, 0).endswith(" LIMIT 100 OFFSET 0"), name)
            self.assertTrue(run.paged(q, 200).endswith(" LIMIT 100 OFFSET 200"), name)
        self.assertEqual(run.PAGE, 100)

    def test_row_queries_return_the_url_for_dedupe(self):
        b = builders()
        for name in ("existing", "existing_all", "week_this"):
            self.assertIn('"url" AS u', b[name])

    def test_paging_reads_every_row_once_in_sqlite(self):
        db = fake_db(250)
        for name in ("existing_all", "week_this"):
            q = run.existing_sql(DS) if name == "existing_all" else run.week_this_sql(DS, "2026-10-01", "2026-10-31")
            got, offsets = read_all(db, q)
            self.assertEqual(offsets, [0, 100, 200], name)               # offsets advance in steps of 100
            urls = [r[4] if name == "existing_all" else r[9] for r in got]
            self.assertEqual(len(urls), 250, name)
            self.assertEqual(len(set(urls)), 250, name)                  # no overlap between pages
        got, offsets = read_all(db, run.existing_sql(DS, "2026-10-26", "2026-10-27"))
        self.assertEqual(len(got), len(set(r[4] for r in got)))
        self.assertEqual(len(got), db.execute('SELECT COUNT(*) FROM "%s" WHERE "date:Date:start" <= \'2026-10-27\''
                                              % DS).fetchone()[0])
        got, offsets = read_all(db, run.week_prev_sql(DS, "2026-10-01", "2026-10-31"))
        self.assertEqual(offsets, [0])
        self.assertEqual(len(got), len({(r[0], r[1], r[2]) for r in got}))
        self.assertEqual(sum(r[4] for r in got), 250)

    def test_exactly_100_rows_reads_one_empty_page_then_stops(self):
        got, offsets = read_all(fake_db(100), run.existing_sql(DS))
        self.assertEqual((len(got), offsets), (100, [0, 100]))


class MorePagesTests(TempWork):
    def rows(self, start, n):
        return [{"k": "key%04d" % i, "d": "2026-11-02", "b": "8:00 am", "a": "Sample %d" % i,
                 "u": "https://www.notion.so/p%04d" % i} for i in range(start, start + n)]

    def save(self, name, n, rows):
        C.write_json(run.page_path(name, n), {"results": rows, "has_more": False})

    def test_sql_prints_page_one(self):
        code, out = call("sql", "--mode", "nightly", "--day", "2026-11-02")
        q = sql_line(out)
        self.assertIn('ORDER BY "Key", "url"', q)
        self.assertTrue(q.endswith("LIMIT 100 OFFSET 0"))
        self.assertNotIn("1000", q)
        self.assertIn("SAVE THE RESULT TO: %s" % run.page_path("existing", 1), out)
        code, out = call("sql", "--mode", "backfill", "--day", "2026-11-02")
        self.assertTrue(sql_line(out).endswith('ORDER BY "Key", "url" LIMIT 100 OFFSET 0'))

    def test_more_advances_offsets_until_a_short_page(self):
        call("sql", "--mode", "nightly", "--day", "2026-11-02")
        self.save("existing", 1, self.rows(0, 100))
        code, out = call("more", "existing")
        self.assertEqual(code, 0)
        self.assertTrue(sql_line(out).endswith("LIMIT 100 OFFSET 100"))
        self.assertIn("SAVE THE RESULT TO: %s" % run.page_path("existing", 2), out)
        self.save("existing", 2, self.rows(100, 100))
        code, out = call("more", "existing")
        self.assertTrue(sql_line(out).endswith("LIMIT 100 OFFSET 200"))
        self.assertEqual(re.sub(r"OFFSET \d+$", "", sql_line(out)),
                         re.sub(r"OFFSET \d+$", "", run.paged(C.read_json(C.wpath("queries.json"))["existing"])))
        self.save("existing", 3, self.rows(200, 37))
        code, out = call("more", "existing")
        self.assertIn("ALL PAGES READ: 237 row(s) in 3 page(s)", out)
        self.assertNotIn("SQL:", out)
        merged = C.read_json(C.wpath("existing.json"))["results"]
        self.assertEqual([r["k"] for r in merged], ["key%04d" % i for i in range(237)])

    def test_overlapping_pages_are_joined_once(self):
        call("sql", "--mode", "nightly", "--day", "2026-11-02")
        self.save("existing", 1, self.rows(0, 100))
        self.save("existing", 2, self.rows(99, 10))                 # row 99 again (a row appeared mid-read)
        code, out = call("more", "existing")
        self.assertIn("ALL PAGES READ: 109 row(s) in 2 page(s)", out)

    def test_more_needs_the_query_and_a_page(self):
        code, out = call("more", "existing")
        self.assertEqual(code, 2)
        self.assertIn("NO QUERY", out)
        call("sql", "--mode", "nightly", "--day", "2026-11-02")
        code, out = call("more", "existing")
        self.assertEqual(code, 2)
        self.assertIn("NO PAGE SAVED", out)

    def test_rerunning_sql_clears_old_pages(self):
        call("sql", "--mode", "nightly", "--day", "2026-11-02")
        self.save("existing", 1, self.rows(0, 100))
        self.save("existing", 2, self.rows(100, 5))
        call("more", "existing")
        call("sql", "--mode", "nightly", "--day", "2026-11-02")
        self.assertEqual(run.page_files("existing"), [])
        self.assertFalse(C.read_json(C.wpath("existing.json")))

    def test_prepare_stops_when_the_pages_were_not_joined(self):
        page = self.write("page.json", page_fetch_json())
        code, out = call("prepare", "--page", page, "--existing", C.wpath("existing.json"), "--day", "2026-11-02")
        self.assertEqual(code, 2)
        self.assertIn("NOT FOUND", out)

    def test_weekly_reads_both_queries_in_pages(self):
        code, out = call("weekly-sql", "--day", "2026-11-01")
        qa, qb = sql_line(out, "SQL A "), sql_line(out, "SQL B ")
        for q in (qa, qb):
            self.assertIn("ORDER BY", q)
            self.assertTrue(q.endswith("LIMIT 100 OFFSET 0"))
            self.assertNotIn("1000", q)
        week = [{"d": "2026-10-27", "b": "8:00 pm", "m": 15, "r": "Sales", "t": "", "k": "Outreach", "ai": "__NO__",
                 "s": "log", "a": "Sample call %d" % i, "u": "https://www.notion.so/w%04d" % i} for i in range(130)]
        self.save("week_this", 1, week[:100])
        code, out = call("more", "week_this")
        self.assertTrue(sql_line(out).endswith("LIMIT 100 OFFSET 100"))
        self.assertIn('ORDER BY "date:Date:start", "url"', sql_line(out))
        self.save("week_this", 2, week[100:])
        code, out = call("more", "week_this")
        self.assertIn("ALL PAGES READ: 130 row(s) in 2 page(s)", out)
        self.save("week_prev", 1, [{"d": "2026-10-20", "r": "Sales", "k": "Outreach", "m": 90, "n": 3}])
        code, out = call("more", "week_prev")
        self.assertIn("ALL PAGES READ: 1 row(s) in 1 page(s)", out)
        code, out = call("weekly", "--this", C.wpath("week_this.json"), "--prev", C.wpath("week_prev.json"),
                         "--day", "2026-11-01")
        self.assertEqual(code, 0)
        roles = {x["role"]: (x["minutes"], x["prev"]) for x in C.read_json(C.wpath("weekly.json"))["roles"]}
        self.assertEqual(roles["Sales"], (130 * 15, 90))                 # all 130 rows, not the first 100
        code, out = call("weekly", "--this", C.wpath("nope.json"), "--prev", C.wpath("week_prev.json"),
                         "--day", "2026-11-01")
        self.assertEqual(code, 2)
        self.assertIn("NOT FOUND", out)


if __name__ == "__main__":
    unittest.main()
