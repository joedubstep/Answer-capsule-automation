import glob
import json
import os
import re
import unittest

from tools.call_engine import rules

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(TOOL))


def rubric():
    with open(os.path.join(TOOL, "rubric.md"), encoding="utf-8") as f:
        return f.read()


class RulesTests(unittest.TestCase):
    def test_all_patterns_compile(self):
        for table in (rules.FLAGS, rules.MOVES, rules.OBJECTIONS):
            for r in table:
                rules.compile_all(r["patterns"])
        rules.compile_all(rules.PROMISE)
        for rx in (rules.MONEY, rules.PRICE_CONTEXT, rules.PROMISE_EXCLUDE, *rules.SIGNAL_WORDS.values()):
            re.compile(rx)

    def test_every_id_is_in_the_rubric(self):
        text = rubric()
        ids = [r["id"] for r in rules.FLAGS + rules.MOVES + rules.OBJECTIONS + rules.REMINDERS + rules.EXPECT]
        ids += [i for i, _ in rules.RUBRIC_ITEMS]
        missing = [i for i in ids if not re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(i), text)]
        self.assertEqual(missing, [])

    def test_ids_unique_and_severities_known(self):
        for table in (rules.FLAGS, rules.MOVES, rules.OBJECTIONS, rules.REMINDERS, rules.EXPECT):
            ids = [r["id"] for r in table]
            self.assertEqual(len(ids), len(set(ids)))
        for f in rules.FLAGS:
            self.assertIn(f["severity"], rules.SEVERITY_ORDER)

    def test_offer_rules_file(self):
        with open(os.path.join(TOOL, "offer_rules.json"), encoding="utf-8") as f:
            o = json.load(f)
        for t in ("route_out", "travel_nurse", "referral_starter", "full_bed_system", "full_bed_system_resident_headline"):
            self.assertIn(t, o["tiers"])
        self.assertNotRegex(json.dumps(o), r"\$\s?\d")             # prices live in Notion, never here

    def test_reminder_text_is_plain(self):
        for r in rules.REMINDERS + rules.EXPECT:
            for v in (r.get("text"), r.get("says"), r.get("move")):
                if v:
                    self.assertNotRegex(v, "[\u2012\u2013\u2014\u2015]")


class PrivacyTests(unittest.TestCase):
    """The repo is public. Nothing this tool ships may hold a real person's email, phone or name."""

    def files(self):
        out = [p for p in glob.glob(os.path.join(TOOL, "**", "*"), recursive=True) if os.path.isfile(p)
               and "__pycache__" not in p]
        out += glob.glob(os.path.join(ROOT, ".claude", "skills", "call_engine", "*"))
        out += [os.path.join(ROOT, "routines", "call_engine.md")]
        return [p for p in out if os.path.exists(p)]

    def test_no_real_emails_or_phones(self):
        ok_domains = ("example.com", "example.org", "example.gov", "example", "surven.ai", "leadsuite.agency",
                      "leadscape.au", "coach.example.org", "vendor.example", "maple.example.com")
        for p in self.files():
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
            for m in re.finditer(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", text):
                dom = m.group(1).lower()
                if "group.calendar.google.com" in dom:
                    continue                                       # a calendar id from config, not a person
                self.assertTrue(dom.endswith(ok_domains), "%s: %s" % (os.path.relpath(p, ROOT), m.group(0)))
            self.assertIsNone(re.search(r"\(\d{3}\)\s?\d{3}-\d{4}|\b\d{3}-\d{3}-\d{4}\b", text),
                              os.path.relpath(p, ROOT))


if __name__ == "__main__":
    unittest.main()
