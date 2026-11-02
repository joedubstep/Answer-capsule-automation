import datetime as dt
import unittest

from tools.time_ledger import report as R


def row(date, block, minutes, role, kind="Other", task="", action="do a thing", source="log", typ="action", ai=False):
    return {"date": date, "block": block, "minutes": minutes, "role": role, "kind": kind, "task": task,
            "action": action, "source": source, "type": typ, "ai": ai}


class NormTests(unittest.TestCase):
    def test_notion_sql_row(self):
        r = R.norm_row({"d": "2026-11-01", "b": "7:30 am", "m": 5, "r": "Admin", "t": "Admin (email, bank, phone)",
                        "k": "Admin", "ai": "__YES__", "s": "log", "a": "check email"})
        self.assertEqual((r["date"], r["minutes"], r["ai"], r["type"]), ("2026-11-01", 5.0, True, "action"))
        b = R.norm_row({"d": "2026-11-01", "b": "4:37 pm", "m": 30, "r": "Not logged", "t": "", "k": "Not logged",
                        "ai": "__NO__", "s": "log", "a": "(blank block)"})
        self.assertEqual(b["type"], "blank")
        br = R.norm_row({"d": "2026-11-01", "r": "Not logged", "t": "Break", "a": "stopping work", "m": 40})
        self.assertEqual(br["type"], "break")

    def test_dedupe_prefers_logged_rows(self):
        rows = [row("2026-11-01", "4:37 pm", 30, "Not logged", typ="blank"),
                row("2026-11-01", "4:37 pm", 30, "Sales", source="inferred"),
                row("2026-11-01", "4:37 pm", 20, "CEO", action="write the application"),
                row("2026-11-01", "7:00 pm", 15, "Not logged", typ="blank"),
                row("2026-11-01", "7:00 pm", 15, "Sales", source="inferred"),
                row("2026-11-01", "8:00 pm", 15, "Not logged", typ="blank")]
        out = R.dedupe(rows)
        self.assertEqual([(r["block"], r["role"]) for r in out],
                         [("4:37 pm", "CEO"), ("7:00 pm", "Sales"), ("8:00 pm", "Not logged")])


class DailyTests(unittest.TestCase):
    def test_daily_numbers(self):
        rows = [row("2026-11-01", "7:30 am", 5, "Admin", "Admin", action="check email"),
                row("2026-11-01", "7:30 am", 15, "Personal", "Distraction", action="reels"),
                row("2026-11-01", "8:00 am", 30, "Sales", "Outreach", action="calls"),
                row("2026-11-01", "9:00 am", 30, "Not logged", "Not logged", typ="blank"),
                row("2026-10-31", "9:00 am", 25, "Personal", "Distraction"),
                row("2026-10-30", "9:00 am", 5, "Personal", "Distraction")]
        d = R.daily(rows, "2026-11-01")
        self.assertEqual(d["work_minutes"], 50)
        self.assertEqual(d["selling_minutes"], 30)
        self.assertEqual(d["distraction_minutes"], 15)
        self.assertEqual(d["streak"], 1)                 # 10/31 had 25 minutes
        self.assertEqual(d["blank_blocks"], 1)
        line = R.daily_line(d, written=4)
        self.assertIn("Nov 1", line)
        self.assertIn("4 new row(s)", line)
        self.assertNotIn("\u2014", line)
        self.assertNotIn("\u2013", line)
        self.assertIn("<html", R.daily_html(d))

    def test_empty_day(self):
        d = R.daily([], "2026-11-01")
        self.assertIn("nothing logged", R.daily_line(d))


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.ws, self.we = dt.date(2026, 10, 26), dt.date(2026, 11, 1)
        days = ["2026-10-%02d" % d for d in (26, 27, 28, 29, 30, 31)] + ["2026-11-01"]
        self.this = []
        for i, d in enumerate(days):
            self.this.append(row(d, "8:00 am", 60, "Sales", "Outreach", action="reactivation calls"))
            self.this.append(row(d, "9:00 am", 10, "Admin", "Admin", task="Admin (email, bank, phone)",
                                 action="check email"))
            self.this.append(row(d, "9:15 am", 25 if i == 2 else 5, "Personal", "Distraction", action="reels"))
            self.this.append(row(d, "10:00 am", 20, "CTO", "Tools", action="send prompt about %s" % ("abcdefg"[i]),
                                 ai=True))
        self.this.append(row("2026-10-29", "1:00 pm", 30, "Not logged", "Not logged", typ="blank"))
        self.this.append(row("2026-10-30", "2:00 pm", 30, "Sales", "Outreach", source="inferred",
                             action="Meeting: sample (inferred)"))
        self.this.append(row("2026-10-30", "2:00 pm", 30, "Not logged", "Not logged", typ="blank"))
        self.prev = [row("2026-10-20", "8:00 am", 30, "Sales", "Outreach"),
                     row("2026-10-21", "8:00 am", 100, "Offer work", "Offer")]

    def test_weekly_numbers(self):
        w = R.weekly(self.this, self.prev, self.ws, self.we)
        roles = {x["role"]: (x["minutes"], x["prev"]) for x in w["roles"]}
        self.assertEqual(roles["Sales"], (420, 30))
        self.assertEqual(roles["Offer work"], (0, 100))
        self.assertEqual(w["selling_minutes"], 420)
        self.assertEqual(w["distraction_minutes"], 55)
        self.assertEqual(w["streak"], 4)                 # Oct 29 to Nov 1 under 20; Oct 28 had 25
        self.assertEqual(w["blank_blocks"], 2)
        self.assertEqual(w["inferred_blocks"], 1)
        self.assertEqual(w["inferred_minutes"], 30)
        self.assertEqual(w["days_logged"], 7)
        self.assertEqual(w["ai_minutes"], 140)
        labels = [c["label"] for c in w["candidates"]]
        self.assertIn("check email", labels)
        self.assertIn("reactivation calls", labels)
        self.assertTrue(any(l.startswith("send prompt") for l in labels))
        self.assertNotIn("reels", labels)                # distractions are not automation candidates
        self.assertLessEqual(len(w["sinks"]), 5)
        self.assertEqual(w["sinks"][0]["label"], "Outreach and calls")

    def test_same_sitting_repeats_are_not_candidates(self):
        rows = [row("2026-10-27", "8:00 pm", 5, "Sales", "Outreach", action="keep filling out the vendor form")
                for _ in range(4)]
        w = R.weekly(rows, [], self.ws, self.we)
        self.assertEqual(w["candidates"], [])

    def test_formats(self):
        w = R.weekly(self.this, self.prev, self.ws, self.we)
        md, txt, page = R.weekly_markdown(w), R.weekly_text(w), R.weekly_html(w, "Nov 01, 11:45 PM ET")
        for s in (md, txt, page):
            self.assertNotIn("\u2014", s)
            self.assertNotIn("\u2013", s)
        self.assertIn("## Time by role vs the week before", md)
        self.assertIn("TOP 5 TIME SINKS", txt)
        self.assertIn("prefers-color-scheme", page)
        self.assertIn("#4e6242", page)
        self.assertIn("Last updated", page)
        self.assertNotIn("<script", page)
        self.assertEqual(R.weekly_title(w), "Time Ledger: week of Oct 26 to Nov 1")

    def test_week_bounds(self):
        self.assertEqual(R.week_bounds(dt.date(2026, 11, 1)), (dt.date(2026, 10, 26), dt.date(2026, 11, 1)))


if __name__ == "__main__":
    unittest.main()
