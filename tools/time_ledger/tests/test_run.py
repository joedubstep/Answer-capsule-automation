import io
import json
import os
import unittest
from contextlib import redirect_stdout

from tools.time_ledger import common as C
from tools.time_ledger import run
from tools.time_ledger.tests.base import TempWork, page_fetch_json


def call(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run.main(list(args))
    return code, buf.getvalue()


class RunTests(TempWork):
    def setUp(self):
        super().setUp()
        self.page = self.write("page.json", page_fetch_json())
        self.empty = self.write("existing.json", json.dumps({"results": [], "has_more": False}))

    def prepare(self, existing=None, mode="nightly", day="2026-11-02"):
        return call("prepare", "--page", self.page, "--existing", existing or self.empty, "--mode", mode,
                    "--day", day)

    def test_sql(self):
        code, out = call("sql", "--mode", "nightly", "--day", "2026-11-02")
        self.assertEqual(code, 0)
        self.assertIn("\"date:Date:start\" >= '2026-11-01' AND \"date:Date:start\" <= '2026-11-02'", out)
        self.assertIn("collection://", out)

    def test_prepare_never_goes_past_the_sql_window(self):
        call("sql", "--mode", "nightly", "--day", "2026-11-02")             # no --page: Nov 1 to Nov 2 only
        code, out = self.prepare()
        self.assertEqual({r["log_date"] for r in C.read_json(C.wpath("new_rows.json"))}, {"2026-11-01", "2026-11-02"})

    def test_sql_window_follows_the_copied_page(self):
        code, out = call("sql", "--mode", "nightly", "--day", "2026-11-02", "--page", self.page)
        self.assertIn("\"date:Date:start\" >= '2026-10-31' AND \"date:Date:start\" <= '2026-11-02'", out)
        code, out = call("sql", "--mode", "nightly", "--day", "2026-11-05", "--page", self.page)
        self.assertIn("\"date:Date:start\" >= '2026-11-02' AND \"date:Date:start\" <= '2026-11-05'", out)
        code, out = call("sql", "--mode", "backfill", "--day", "2026-11-02", "--page", self.page)
        self.assertIn("\"date:Date:start\" >= '2026-10-24' AND \"date:Date:start\" <= '2026-11-02'", out)
        p = self.write("nolog2.md", "# nothing here\n")
        code, out = call("sql", "--mode", "nightly", "--day", "2026-11-02", "--page", p)
        self.assertIn("NO LOG FOUND", out)

    def test_nightly_end_to_end(self):
        code, out = self.prepare()
        self.assertEqual(code, 0)
        self.assertIn("DATE CHECK: '15 min log 11/1' -> 2026-11-02", out)
        new = C.read_json(C.wpath("new_rows.json"))
        # the log day, the day before, and any day up to 3 back that the copied page holds
        self.assertEqual({r["log_date"] for r in new}, {"2026-10-31", "2026-11-01", "2026-11-02"})
        need = C.read_json(C.wpath("needs_label.json"))
        self.assertTrue(need)
        labels = {need[0]["key"]: {"role": "Admin", "kind": "Admin", "task": "Admin (email, bank, phone)",
                                   "ai": False},
                  "bogus": {"role": "Admin"}}
        if len(need) > 1:
            labels[need[1]["key"]] = {"role": "Not a role"}
        lab = self.write("labels.json", json.dumps(labels))
        ev = self.write("evidence.json", json.dumps([{"source": "calendar", "start": "2026-11-01T18:30:00-05:00",
                                                       "end": "2026-11-01T19:00:00-05:00", "title": "Sample call",
                                                       "attendees": 1}]))
        code, out = call("build", "--labels", lab, "--evidence", ev)
        self.assertEqual(code, 0)
        self.assertIn("LABELS APPLIED: 1", out)
        self.assertIn("INFERRED: 1 row(s) for 1 blank block(s)", out)
        batch = C.read_json(C.wpath("batches/batch_01.json"))
        self.assertEqual(batch["parent"]["type"], "data_source_id")
        props = [p["properties"] for p in batch["pages"]]
        self.assertEqual(set(props[0]), {"Action", "date:Date:start", "date:Date:is_datetime", "Block start",
                                         "Minutes (est)", "Role", "Task", "Kind", "AI", "Confidence", "Source",
                                         "Key"})
        roles = set(C.ROLES) | {C.NOT_LOGGED}
        self.assertTrue(all(p["Role"] in roles for p in props))
        self.assertTrue(all(p["AI"] in ("__YES__", "__NO__") for p in props))
        self.assertTrue(all(p["Action"] for p in props))
        by_key = {p["Key"]: p for p in props}
        self.assertEqual(by_key[need[0]["key"]]["Role"], "Admin")
        inferred = [p for p in props if p["Source"] == "inferred"]
        self.assertEqual(len(inferred), 1)
        self.assertEqual(inferred[0]["Block start"], "4:37 pm")
        # the blank row of the filled block is not written; the other blanks are
        self.assertFalse([p for p in props if p["Block start"] == "4:37 pm" and p["Action"] == C.BLANK_TEXT])
        self.assertTrue([p for p in props if p["Block start"] == "7:00 pm" and p["Action"] == C.BLANK_TEXT])
        code, out = call("finish", "--written", str(len(props)))
        self.assertTrue(out.startswith("Time Ledger Nov 2:"))
        self.assertIn("%d new row(s)" % len(props), out)
        self.assertTrue(os.path.exists(C.wpath("daily.html")))

    def test_daily_summary_uses_claude_labels(self):
        self.prepare()
        need = [n for n in C.read_json(C.wpath("needs_label.json")) if n["date"] == "2026-11-02"]
        self.assertTrue(need, "the synthetic page should have an unsure row on the log day")
        lab = self.write("labels.json", json.dumps({need[0]["key"]: {"role": "HR and hiring", "kind": "Other",
                                                                      "task": "Other", "ai": False}}))
        call("build", "--labels", lab)
        call("finish", "--dry-run")
        with open(C.wpath("daily.md"), encoding="utf-8") as f:
            self.assertIn("HR and hiring", f.read())

    def test_second_run_writes_nothing(self):
        self.prepare()
        call("build")
        props = [p["properties"] for p in C.read_json(C.wpath("batches/batch_01.json"))["pages"]]
        existing = {"results": [{"k": p["Key"], "d": p["date:Date:start"], "b": p["Block start"], "a": p["Action"]}
                                for p in props], "has_more": False}
        ex = self.write("existing2.json", json.dumps(existing))
        code, out = self.prepare(existing=ex)
        self.assertIn("NOTHING NEW", out)
        self.assertEqual(C.read_json(C.wpath("new_rows.json")), [])

    def test_edited_and_redated_rows_are_not_duplicated(self):
        self.prepare()
        new = C.read_json(C.wpath("new_rows.json"))
        act = [r for r in new if r["type"] == "action"]
        a, b = act[0], act[1]
        existing = {"results": [
            {"k": "old1", "d": a["log_date"], "b": a["block_label"], "a": a["action_text"] + " today"},
            {"k": "old2", "d": "2026-10-31", "b": b["block_label"], "a": b["action_text"]}]}
        ex = self.write("existing3.json", json.dumps(existing))
        code, out = self.prepare(existing=ex)
        keys = {r["key"] for r in C.read_json(C.wpath("new_rows.json"))}
        self.assertNotIn(a["key"], keys)
        self.assertNotIn(b["key"], keys)
        self.assertIn("2 edited or re-dated", out)

    def test_similar_rows_still_written_after_partial_write(self):
        self.prepare()
        new = C.read_json(C.wpath("new_rows.json"))
        first = [r for r in new if r["type"] == "action"][0]
        # Notion has only the first row, under its current key: siblings with similar words are still new
        existing = {"results": [{"k": first["key"], "d": first["log_date"], "b": first["block_label"],
                                 "a": first["action_text"]}]}
        ex = self.write("existing4.json", json.dumps(existing))
        code, out = self.prepare(existing=ex)
        self.assertIn("0 edited or re-dated", out)
        self.assertEqual(len(C.read_json(C.wpath("new_rows.json"))), len(new) - 1)

    def test_same_action_same_minute_next_day_is_new(self):
        rows = [{"type": "action", "block_label": "8:00 am", "action_text": "check email", "log_date": "2026-11-02",
                 "key": "k2"}]
        orphans = run.unmatched_rows([{"k": "k1", "d": "2026-11-01", "b": "8:00 am", "a": "check email"}],
                                     [dict(rows[0], key="k1", log_date="2026-11-01")] + rows)
        self.assertEqual(orphans, [])                     # yesterday's row still matches yesterday on the page
        self.assertFalse(run.take_orphan(orphans, rows[0]))
        orphans = run.unmatched_rows([{"k": "gone", "d": "2026-11-01", "b": "8:00 am", "a": "check email"}], rows)
        self.assertTrue(run.take_orphan(orphans, rows[0]))  # yesterday's row vanished: this is it, re-dated
        self.assertFalse(run.take_orphan(orphans, rows[0]))  # and it can stand in only once

    def test_backfill_covers_every_day(self):
        code, out = self.prepare(mode="backfill")
        days = {r["log_date"] for r in C.read_json(C.wpath("new_rows.json"))}
        self.assertEqual(days, {"2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-31",
                                "2026-11-01", "2026-11-02"})
        call("build")
        files = C.read_json(C.wpath("state.json"))["batches"]
        self.assertGreaterEqual(len(files), 2)                      # 50 rows per batch file
        code, out = call("finish", "--dry-run")
        self.assertIn("dry run: nothing written", out)
        self.assertIn("backfill window 2026-10-24 to 2026-11-02", out)

    def test_no_log_on_page(self):
        p = self.write("nolog.md", "# Just a page\n\n- [ ] a task\n")
        code, out = call("prepare", "--page", p, "--existing", self.empty, "--day", "2026-11-02")
        self.assertEqual(code, 3)
        self.assertIn("NO LOG FOUND", out)
        code, out = call("finish")
        self.assertIn("no 15-minute log found", out)

    def test_weekly_from_page_and_from_notion(self):
        self.prepare(mode="backfill")
        call("build")
        code, out = call("weekly", "--from-page", "--day", "2026-11-01")
        self.assertEqual(code, 0)
        self.assertIn("WEEKLY READY: Time Ledger: week of Oct 26 to Nov 1", out)
        email = C.read_json(C.wpath("email.json"))
        cfg = C.load_config()
        self.assertEqual(email["to"], [cfg["google"]["joey_gmail"]])
        self.assertNotIn("\u2014", email["body"] + email["htmlBody"])
        page = C.read_json(C.wpath("notion_page.json"))
        self.assertEqual(page["parent"]["page_id"], cfg["notion"]["automations_home"])
        self.assertIn("## Top 5 time sinks", page["pages"][0]["content"])
        # the Notion SQL path: this week's rows and last week's totals
        rows = [{"d": "2026-10-27", "b": "8:00 pm", "m": 30, "r": "Sales", "t": "", "k": "Outreach",
                 "ai": "__NO__", "s": "log", "a": "reactivation calls"},
                {"d": "2026-10-28", "b": "8:00 pm", "m": 10, "r": "Personal", "t": "", "k": "Distraction",
                 "ai": "__NO__", "s": "log", "a": "reels"}]
        prev = [{"d": "2026-10-20", "r": "Sales", "k": "Outreach", "m": 90, "n": 3}]
        a = self.write("a.json", json.dumps({"results": rows, "has_more": False}))
        b = self.write("b.json", json.dumps({"results": prev, "has_more": False}))
        code, out = call("weekly-sql", "--day", "2026-11-01")
        self.assertIn("WEEK: 2026-10-26 to 2026-11-01 (compared with 2026-10-19 to 2026-10-25)", out)
        code, out = call("weekly", "--this", a, "--prev", b, "--day", "2026-11-01")
        w = C.read_json(C.wpath("weekly.json"))
        roles = {x["role"]: (x["minutes"], x["prev"]) for x in w["roles"]}
        self.assertEqual(roles["Sales"], (30, 90))
        self.assertEqual(w["distraction_minutes"], 10)

    def test_weekly_adds_rows_written_this_run_that_sql_missed(self):
        self.prepare(mode="backfill", day="2026-11-01")
        call("build")
        n = len(C.read_json(C.wpath("write_rows.json"))) - 3          # the last batch call wrote all but 3
        call("finish", "--written", str(n))
        written = C.read_json(C.wpath("write_rows.json"))[:n]
        week = [r for r in written if "2026-10-26" <= r["log_date"] <= "2026-11-01"]
        self.assertTrue(week)
        empty = self.write("a0.json", json.dumps({"results": []}))
        code, out = call("weekly", "--this", empty, "--prev", empty, "--day", "2026-11-01")
        self.assertIn("ADDED %d row(s)" % len(week), out)
        # when the SQL read already shows them, nothing is counted twice
        shown = [{"d": r["log_date"], "b": r["block_label"], "m": r["minutes"], "r": r["role"], "t": r["task"],
                  "k": r["kind"], "ai": "__NO__", "s": r["source"],
                  "a": r["action_text"] if r["type"] != "blank" else C.BLANK_TEXT} for r in week]
        full = self.write("a1.json", json.dumps({"results": shown}))
        code, out = call("weekly", "--this", full, "--prev", empty, "--day", "2026-11-01")
        self.assertNotIn("ADDED", out)

    def test_email_only_to_joey(self):
        from unittest import mock
        cfg = C.load_config()
        cfg["google"] = dict(cfg["google"], joey_gmail="someone@example.com")
        empty = self.write("a0.json", json.dumps({"results": []}))
        with mock.patch.object(run.C, "load_config", return_value=cfg):
            code, out = call("weekly", "--this", empty, "--prev", empty, "--day", "2026-11-01")
        self.assertIn("EMAIL BLOCKED", out)
        self.assertEqual(C.read_json(C.wpath("email.json"))["to"], [])
        code, out = call("weekly", "--this", empty, "--prev", empty, "--day", "2026-11-01")
        self.assertEqual(C.read_json(C.wpath("email.json"))["to"], [C.load_config()["google"]["joey_gmail"]])
        self.assertFalse(run.allowed_recipient("someone@example.com"))
        self.assertFalse(run.allowed_recipient(""))

    def test_weekly_on_a_weekday_reports_last_full_week(self):
        code, out = call("weekly-sql", "--day", "2026-11-04")
        self.assertIn("WEEK: 2026-10-26 to 2026-11-01", out)


if __name__ == "__main__":
    unittest.main()
