import html
import json
import re

from tools.ls_evidence import render
from tools.ls_evidence import score as S
from tools.ls_evidence.tests import fixtures as fx
from tools.ls_evidence.tests.base import FakeGHL


class RenderTest(FakeGHL):
    def setUp(self):
        super().setUp()
        self.ev = self.evidence()
        self.h = render.render(self.ev)

    def test_page_contract(self):
        h = self.h
        self.assertTrue(h.startswith('<title>Lead Suite Evidence</title>\n<meta name="claude:viewport-fit-sides" '
                                     'content="cover">'))
        self.assertNotIn("<html", h.lower())
        self.assertNotIn("<body", h.lower())
        for color in ("#f2eee3", "#faf7ef", "#4e6242", "#181b18", "#c8c1b1"):
            self.assertIn(color, h)
        self.assertIn("prefers-color-scheme: dark", h)
        self.assertIn(':root:not([data-theme="light"])', h)
        self.assertIn(':root[data-theme="dark"]', h)
        self.assertIn("max(16px, env(safe-area-inset-left, 0px))", h)
        self.assertNotRegex(h, r"<script[^>]+src=")
        self.assertNotRegex(h, r"<link[^>]+href=")
        self.assertIn("Last updated Sun Nov 8, 6am ET", h)

    def test_order_scoreboard_then_portal_then_evidence(self):
        a = self.h.index("Refund scoreboard")
        b = self.h.index("Rows to enter in the portal</h2>")
        c = self.h.index("Evidence for the refund file")
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_top_line_and_scoreboard(self):
        self.assertIn("<h1>3 of 30 qualified calls, 8 days left, 10 portal rows to enter</h1>", self.h)
        self.assertIn("Where the refund case stands:</strong> 3 of 30 qualified calls with 8 days left.", self.h)
        self.assertIn("Sat Aug 8 to Mon Nov 16, 11 paused days skipped", self.h)
        self.assertIn("Outside GHL", self.h)
        self.assertIn("Meta Ads Manager", self.h)
        self.assertIn("Mercury", self.h)

    def test_portal_rows_in_box_order_with_copy(self):
        pat = next(r for r in self.ev["leads"] if r["first"] == "Pat")
        uid = "pl" + pat["hash"]
        m = re.search(r'<pre class="text" id="%s">(.*?)</pre>' % uid, self.h, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(html.unescape(m.group(1)).split("\n"), [
            "Pat (41), lead in Mon Oct 19, 10am ET",
            "1. Triple dial within 3 to 5 min of the form fill: Yes",
            "2. SMS 1 within 5 min: Yes",
            "3. Double dial right after a reply: Not due",
            "4. SMS 2 at 3 to 4 hours: Yes",
            "5. SMS 3 at 2 to 3 hours after SMS 2: Yes",
            "6. Lead replied: No"])
        self.assertIn(f'data-target="{uid}">Copy</button>', self.h)
        self.assertEqual(self.h.count('<li class="row'), 10)       # 7 leads and 3 calls
        self.assertIn(">Copy all 7</button>", self.h)

    def test_call_row_has_notes_stub(self):
        sam = next(r for r in self.ev["calls"] if r["first"] == "Sam")
        m = re.search(r'id="pc%s">(.*?)</pre>' % sam["hash"], self.h, re.S)
        lines = html.unescape(m.group(1)).split("\n")
        self.assertEqual(lines[0], "Sam (12), call Thu Oct 22, 2pm ET")
        self.assertEqual(lines[1:6], ["1. Triage call before the main call: Yes", "2. Show-rate SOP followed: Yes",
                                      "3. Pre-call video email the evening before: Yes",
                                      "4. Morning confirm call or text: Yes", "5. Showed: Yes"])
        self.assertTrue(lines[6].startswith("Notes: OUTCOME: Talked 30 min."))
        tay = next(r for r in self.ev["calls"] if r["first"] == "Taylor")
        self.assertIn("from the GHL note", self.h)
        self.assertIn(f'id="pc{tay["hash"]}"', self.h)

    def test_waiting_and_first_run(self):
        self.assertIn("First run: every finished row since ads went live is listed.", self.h)
        self.assertIn("Not finished yet (still inside their text windows), so not listed: Jordan (90).", self.h)
        self.assertIn("Not finished yet (the call has not happened yet), so not listed: Casey (60).", self.h)

    def test_checks_shown(self):
        self.assertIn("Check: Triple dial within 3 to 5 min of the form fill: GHL field says Yes", self.h)

    def test_evidence_tables_and_tsv(self):
        self.assertIn("<h3>Leads: 9</h3>", self.h)              # includes Kim, marked as a duplicate
        self.assertIn("duplicate of an earlier lead", self.h)
        self.assertIn("<h3>Booked calls: 5</h3>", self.h)        # includes Casey's moved booking
        m = re.search(r'<pre class="tsv" id="tsvl">(.*?)</pre>', self.h, re.S)
        rows = html.unescape(m.group(1)).split("\n")
        self.assertEqual(len(rows), 10)
        self.assertTrue(rows[0].startswith("Lead\tCode\tLead in (ET)"))
        self.assertIn("Yes (3 dials by 10:04am, 4 min after the form)", rows[1])
        self.assertIn('data-target="tsvc"', self.h)

    def test_no_phone_numbers_or_emails_or_last_names(self):
        self.assertNotRegex(self.h, r"\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b")
        self.assertNotRegex(self.h, r"[\w.+-]+@[\w-]+\.[\w.]+")
        for last in ("Example", "Sample", "Placeholder", "Demo"):
            self.assertNotIn(last, self.h)

    def test_no_dashes_and_no_forbidden_words(self):
        low = self.h.lower()
        self.assertNotIn("—", self.h)
        self.assertNotIn("–", self.h)
        self.assertNotIn("chargeback", low)
        self.assertNotIn("recording", low)

    def test_state_block_round_trip(self):
        m = re.search(r'id="ls-state">(.*?)</script>', self.h, re.S)
        st = json.loads(m.group(1))
        self.assertEqual(st, self.ev["state"])
        self.assertEqual(len(st["rows"]), 10)
        self.assertTrue(all(re.match(r"^[LC][0-9a-f]{12}$", k) for k in st["rows"]))
        blob = json.dumps(st)
        self.assertNotIn("Pat", blob)
        self.assertNotIn("cPat", blob)

    def test_read_prev_state_from_a_page_file(self):
        import os
        path = os.path.join(self.tmp, "prev.html")
        with open(path, "w") as f:
            f.write(self.h)
        self.assertEqual(S.read_prev_state(path), self.ev["state"])
        with open(path, "w") as f:
            f.write("<title>x</title>")
        self.assertIsNone(S.read_prev_state(path))
        self.assertIsNone(S.read_prev_state(None))

    def test_copy_js_has_a_fallback(self):
        self.assertIn("navigator.clipboard", self.h)
        self.assertIn("execCommand('copy')", self.h)
        self.assertIn("'Selected'", self.h)

    def test_test_run_eyebrow(self):
        ev = dict(self.ev, location_key="agc")
        self.assertIn("Test run on AGC data", render.render(ev))


class EmptyPageTest(FakeGHL):
    drop = ("contacts__search.json", "opportunities__search.json", "calendars__events.json")

    def test_empty_states(self):
        ev = self.evidence()
        h = render.render(ev)
        self.assertIn("No Lead Suite leads since ads went live.", h)
        self.assertIn("No new leads to enter.", h)
        self.assertIn("<h1>0 of 30 qualified calls, 8 days left, 0 portal rows to enter</h1>", h)
        self.assertIn("GHL reads failed this run", h)
