import json
import re

from tools.hq_desk import render, drafts
from tools.hq_desk.tests.base import FakeGHL


class RenderTest(FakeGHL):
    def page(self, desk=None):
        return render.render(desk or self.desk())

    def test_page_contract(self):
        h = self.page()
        self.assertTrue(h.startswith("<title>HQ Deal Desk</title>"))
        self.assertNotIn("<html", h.lower())
        self.assertNotIn("<body", h.lower())
        for color in ("#f2eee3", "#faf7ef", "#4e6242", "#181b18", "#c8c1b1"):
            self.assertIn(color, h)
        self.assertIn("prefers-color-scheme: dark", h)
        self.assertIn(':root[data-theme="dark"]', h)
        self.assertIn("max(16px, env(safe-area-inset-left, 0px))", h)
        self.assertNotRegex(h, r"<script[^>]+src=")              # no external scripts
        self.assertIn("Last updated Mon Nov 2, 6am ET", h)

    def test_top_line(self):
        h = self.page()
        self.assertIn("<h1>2 owners to call today, 2 owed items waiting, 1 call booked next week</h1>", h)

    def test_no_phone_numbers_or_emails(self):
        h = self.page()
        self.assertNotRegex(h, r"\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b")
        self.assertNotRegex(h, r"[\w.+-]+@[\w-]+\.[\w.]+")
        self.assertNotIn("Example Person", h)

    def test_no_dashes_in_page_copy(self):
        h = self.page()
        self.assertNotIn("\u2014", h)
        self.assertNotIn("\u2013", h)

    def test_cards_name_home_code(self):
        h = self.page()
        self.assertIn("Pat <span class=\"home\">Maple Example Home</span>", h)
        self.assertIn('data-copy="41"', h)
        self.assertIn('data-copy="E24"', h)
        self.assertIn('class="code none">no code', h)        # warm referral with no code yet
        self.assertEqual(h.count('<li class="lead"'), 5)
        self.assertIn("<details class=\"owed\"><summary>Owed: 2 items, oldest 13 days</summary>", h)

    def test_red_only_when_red(self):
        h = self.page()
        reds = re.findall(r'<li class="flag red">.*?</li>', h)
        self.assertEqual(len(reds), 1)
        self.assertIn("got no answer for over 24 hours", reds[0])
        self.assertIn("<strong>", reds[0])
        self.assertNotIn("<strong>1 discovery call", h)

    def test_state_block(self):
        desk = self.desk()
        h = self.page(desk)
        m = re.search(r'id="desk-state">(.*?)</script>', h, re.S)
        st = json.loads(m.group(1))
        self.assertEqual(st["red"], ["unanswered"])
        self.assertEqual(len(st["hot"]), 1)
        self.assertNotIn("cHot0001", m.group(1))               # hashed, never the raw id

    def test_drafts_and_held_drafts(self):
        desk = self.desk()
        hot = next(l for l in desk["items"] if l["code"] == "41")
        dec = next(l for l in desk["items"] if l["code"] == "12")
        desk, _, held = drafts.merge(desk, {
            hot["id"]: {"sms": "I can call at 3:30 today. Does that work?"},
            dec["id"]: {"sms": "Quick one \u2014 any questions?",
                        "owed": [{"for": 0, "kind": "email", "subject": "The Loom", "text": "Here is the Loom.",
                                  "sources": ["https://example.org/rule", "javascript:alert(1)"]},
                                 {"for": 1, "kind": "note", "missing": "Your notes from the county call.",
                                  "done": "plan log says sent 10/30"}]},
        })
        self.assertEqual(held, 1)
        h = self.page(desk)
        self.assertIn("I can call at 3:30 today. Does that work?", h)
        self.assertNotIn("Quick one", h)                         # held text never reaches the page
        self.assertIn("Held by the copy checker", h)
        self.assertIn("Copy subject", h)
        self.assertIn('href="https://example.org/rule"', h)
        self.assertNotIn("javascript:", h)
        self.assertIn("Needs from you: Your notes from the county call.", h)
        self.assertIn("Looks done already: plan log says sent 10/30", h)
        self.assertIn("1 owed item ready", h)

    def test_hidden_and_cap(self):
        desk = self.desk()
        desk["cap"] = 2
        first = desk["items"][0]
        first["drafts"] = {"hide": "auto reply, not a person"}
        h = self.page(desk)
        self.assertEqual(h.count('<li class="lead"'), 2)
        self.assertNotIn(f'id="l{first["hash"]}"', h)
        self.assertIn("Left off after review: 1.", h)
        self.assertIn("2 more are in the follow-up planner", h)

    def test_empty_desk(self):
        desk = self.desk()
        desk["items"] = []
        self.assertIn("Nobody needs you right now", self.page(desk))
