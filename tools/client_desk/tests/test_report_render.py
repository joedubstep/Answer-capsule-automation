"""Friday owner report and both pages: honest numbers, client-safe words, brand, no personal data on the page."""
import re

from tools.client_desk import report as R
from tools.client_desk import render as RD
from tools.client_desk.tests.base import FakeGHL

PII = re.compile(r"\+?\d[\d\s().-]{8,}\d|[\w.+-]+@[\w-]+\.[\w.]+")


def text_of(h):
    h = re.sub(r"(?is)<(style|script)>.*?</\1>", " ", h)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


class Report(FakeGHL):
    def test_sentences_match_the_numbers(self):
        v = self.view("friday")
        rep = v["report"]
        txt = R.plain_text(rep)
        self.assertIn("2 new families came in this week.", txt)
        self.assertIn("1 came from a text.\n1 came from the website.", txt)
        self.assertIn("within 4 minutes", txt)
        self.assertIn("1 of 3 move-ins so far.", txt)
        self.assertIn("No Answer: 1.", txt)
        self.assertIn("We made 2 calls, sent 1 text and 2 emails", txt)
        self.assertIn("The target was 30 partners on the weekly email and 6 referrals by Oct 30. Now: 3 and 1.", txt)
        self.assertIn("9 new numbers with no name called or texted.", txt)
        self.assertIn("5 look like robocalls.", txt)
        nxt = next(s for s in rep["sections"] if s["key"] == "next")["bullets"]
        self.assertIn("Call the 2 partners we have not reached yet.", nxt)
        self.assertIn("Send the open rooms email to 2 partners on Monday.", nxt)

    def test_copy_check_passes(self):
        rep = self.view("friday")["report"]
        self.assertTrue(rep["check"]["page"]["ok"], rep["check"]["page"])
        self.assertTrue(rep["check"]["text"]["ok"], rep["check"]["text"])
        low = (R.plain_text(rep) + rep["text"]).lower()
        for bad in ("leads", "care home", "patients", "enquir", "\u2014", "\u2013"):
            self.assertNotIn(bad, low)

    def test_zero_is_zero(self):
        v = self.view("friday")
        d = v["desk"]
        d["families"].update(new_week=0, new_by_way={}, speed_week_n=0, speed_week_min=None, speed_month_n=0,
                             speed_month_min=None, reached_week=0, unknown_callers_week=0)
        d["tours"].update(held_week=0, upcoming=0, toured_to_date=0, booked_week=0)
        d["move_ins"].update(to_date=0, week=0)
        rep = R.build(d, {})
        txt = R.plain_text(rep)
        self.assertIn("No new families came in this week.", txt)
        self.assertIn("there is no speed to report", txt)
        self.assertIn("No tours happened this week.", txt)
        self.assertIn("0 of 3 move-ins so far.", txt)
        self.assertIn("Move-ins: 0 of 3", rep["text"])

    def test_short_text(self):
        t = self.view("friday")["report"]["text"]
        self.assertLessEqual(len(t.splitlines()), 10)
        self.assertTrue(t.startswith("Sample Grove Home this week ("))

    def test_report_page(self):
        v = self.view("friday")
        h = RD.render_report(v["report"], "AGC")
        self.assertIn("<title>AGC Weekly Report</title>", h)
        for c in ("#f2eee3", "#4e6242", "#181b18", "Cormorant Garamond", "DM Sans"):
            self.assertIn(c, h)
        self.assertNotIn("<script", h)
        self.assertNotRegex(h, r"<link|src=\"http|@import")
        self.assertIn("prefers-color-scheme: dark", h)
        self.assertIn("@media print", h)
        self.assertIsNone(PII.search(text_of(h)))

    def test_note_from_model(self):
        v = self.view("friday")
        rep = R.build(v["desk"], v["report_counts"], note="The new room photos went up this week.")
        self.assertEqual(rep["sections"][-1]["lines"], ["The new room photos went up this week."])


class Page(FakeGHL):
    def page(self, mode):
        return RD.render_page(self.view(mode))

    def test_monday_page(self):
        h = self.page("monday")
        t = text_of(h)
        self.assertIn("<title>AGC Client Desk</title>", h)
        self.assertIn("Last updated Fri Nov 6, 7:00am ET", t)
        for s in ("Unknown callers", "Partner calls this week", "Open rooms email", "Partner pipeline",
                  "Waiting over 24 hours", "Copy answers", "Copy email", "Copy subject"):
            self.assertIn(s, t)
        self.assertIn("<mark>[N]</mark>", h)
        self.assertNotIn("Owner report", t)
        self.assertIsNone(PII.search(t), PII.search(t))

    def test_friday_page(self):
        v = self.view("friday")
        v["report_url"] = "https://claude.ai/artifact/report-page"
        h = RD.render_page(v)
        t = text_of(h)
        for s in ("Owner report", "Open report page", "Copy short text", "Unknown callers"):
            self.assertIn(s, t)
        self.assertIn('href="https://claude.ai/artifact/report-page"', h)
        self.assertNotIn('href="report.html"', h)          # the report is its own artifact, never a relative file
        self.assertNotIn("Partner calls this week", t)
        self.assertIsNone(PII.search(t))

    def test_friday_page_before_first_report_publish(self):
        v = self.view("friday")
        v["report_url"] = ""  # independent of the live config, which has the report link filled in
        t = text_of(RD.render_page(v))
        self.assertNotIn("Open report page", t)
        self.assertIn("its link is in this run", t)

    def test_plurals(self):
        v = self.view("monday")
        t = text_of(RD.render_page(v))
        self.assertNotRegex(t, r"\b1 (days|partners|touches|check-ins)\b")
        rep = self.view("friday")["report"]
        self.assertIn("Follow up with the 1 family who toured or is deciding.",
                      next(s for s in rep["sections"] if s["key"] == "next")["bullets"])

    def test_speed_lines_say_how_many(self):
        txt = R.plain_text(self.view("friday")["report"])
        self.assertIn("1 new family heard from us this week, within 4 minutes.", txt)
        self.assertIn("1 new family has no call or text from us on record yet.", txt)
        self.assertIn("Over the last 30 days, 2 new families heard from us.", txt)

    def test_page_contract(self):
        h = self.page("full")
        self.assertIn(':root:not([data-theme="light"])', h)
        self.assertIn(':root[data-theme="dark"]', h)
        self.assertIn("body { margin: 0; background: var(--bg)", h)
        self.assertIn("max(16px", h)
        self.assertNotRegex(h, r"<script src|<link ")
        self.assertNotRegex(h, "[\u2012-\u2015]")

    def test_held_report_is_not_shown(self):
        v = self.view("friday")
        v["report"]["check"]["page"] = {"ok": False, "checker": "copy_check", "warns": [],
                                        "blocks": [{"rule": "dash", "match": "-", "fix": "x", "line": 1}], "grade": 1}
        t = text_of(RD.render_page(v))
        self.assertIn("Held by the copy checker", t)
        self.assertNotIn("Copy short text", t)

    def test_top_line(self):
        v = self.view("monday")
        line = RD.top_line(v)
        self.assertTrue(line.startswith("AGC Monday: 2 partners to call, 1 check-in;"))
        self.assertIn("open rooms email ready for 2", line)
        self.assertIn("2 family", line)
