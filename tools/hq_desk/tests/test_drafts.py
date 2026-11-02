import os
import tempfile
import unittest

from tools.hq_desk import drafts
from tools.hq_desk.tests.base import FakeGHL

FAKE_CHECKER = """
import argparse, json, sys
ap = argparse.ArgumentParser()
ap.add_argument("--context", required=True)
ap.add_argument("--file", required=True)
ap.add_argument("--json", action="store_true")
a = ap.parse_args()
t = open(a.file, encoding="utf-8").read()
issues = []
if "BAD" in t:
    issues.append({"rule": "fake_block", "severity": "block", "match": "BAD", "line": 1, "fix": "remove BAD"})
if "meh" in t:
    issues.append({"rule": "fake_warn", "severity": "warn", "match": "meh", "line": 1, "fix": "plainer"})
ok = not any(i["severity"] == "block" for i in issues)
print(json.dumps({"ok": ok, "issues": issues, "context": a.context}, indent=2))
sys.exit(0 if ok else 1)
"""


class BasicCheckTest(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("HQ_DESK_COPY_CHECK", None)

    def tearDown(self):
        if self._old:
            os.environ["HQ_DESK_COPY_CHECK"] = self._old

    def test_blocks(self):
        for bad in ("Quick one \u2014 call?", "Your care home has room?", "Reply STOP to end", "Is now a bad time?",
                    "Our patients love it", "Great news \U0001F600"):
            self.assertEqual(drafts.basic_check(bad, "prospect_sms")["status"], "blocked", bad)

    def test_warns(self):
        r = drafts.basic_check("It is $4,500 for 90 days. Want it? Or not?", "prospect_sms")
        self.assertEqual(r["status"], "warn")
        self.assertEqual({i["rule"] for i in r["issues"]}, {"price", "one ask"})

    def test_clean(self):
        r = drafts.basic_check("I can call at 3:30 today. Does that work?", "prospect_sms")
        self.assertEqual(r, {"status": "ok", "issues": [], "checker": "basic"})

    def test_internal_note_allows_plain_words(self):
        self.assertEqual(drafts.basic_check("Ask the care home owner for the county form.", "internal")["status"], "ok")


@unittest.skipUnless(os.path.exists(drafts.CHECKER), "tools/copy_check not in this checkout")
class RealCheckerTest(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("HQ_DESK_COPY_CHECK", None)

    def tearDown(self):
        if self._old:
            os.environ["HQ_DESK_COPY_CHECK"] = self._old

    def test_real_checker(self):
        held = drafts.copy_check("Quick one \u2014 any questions?", "prospect_sms")
        self.assertEqual((held["status"], held["checker"]), ("blocked", "copy_check"))
        good = drafts.copy_check("I can call at 3:30 today. Does that work?", "prospect_sms")
        self.assertNotEqual(good["status"], "blocked", good)


class MergeRulesTest(FakeGHL):
    def setUp(self):
        super().setUp()
        self._old_cc = os.environ.pop("HQ_DESK_COPY_CHECK", None)

    def tearDown(self):
        if self._old_cc:
            os.environ["HQ_DESK_COPY_CHECK"] = self._old_cc
        super().tearDown()

    def test_phone_or_email_is_held(self):
        desk = self.desk()
        ids = {l["code"]: l["id"] for l in desk["items"]}
        desk, report, held = drafts.merge(desk, {
            ids["41"]: {"sms": "Call me at 555-201-4477 today. Does that work?"},
            ids["E24"]: {"email_subject": "Open beds", "email": "Write to pat@example.com with the form."},
        })
        self.assertEqual(held, 2)
        self.assertTrue(any("HELD 41 text" in r and "no phone or email" in r for r in report))

    def test_owed_for_must_match_an_item(self):
        desk = self.desk()
        sam = next(l for l in desk["items"] if l["code"] == "12")
        due = [x for x in sam["owed"] if x["due"]]
        desk, report, _ = drafts.merge(desk, {sam["id"]: {"owed": [
            {"for": 7, "kind": "email", "text": "Here is the Loom."},
            {"for": due[1]["text"], "kind": "note", "text": "Ask the county office first."},
            {"for": "0", "kind": "email", "text": "Here is the Loom link."}]}})
        rows = sam["drafts"]["owed"]
        self.assertEqual(sorted(r["for"] for r in rows), [0, 1])     # text and digit string both resolve
        self.assertTrue(any("skip 12 owed for=7" in r for r in report))

    def test_rerun_starts_clean(self):
        desk = self.desk()
        ids = {l["code"]: l["id"] for l in desk["items"]}
        desk, _, _ = drafts.merge(desk, {ids["41"]: {"sms": "I can call at 3:30 today. Does that work?"}})
        desk, _, _ = drafts.merge(desk, {ids["E24"]: {"hide": "answered in Gmail"}})
        d = {l["code"]: l for l in desk["items"]}
        self.assertEqual(d["41"]["drafts"], {})
        h = {f["key"]: f for f in desk["health"]}
        self.assertEqual(h["unanswered"]["count"], 0)              # merge applies the hides to the flags


class CopyCheckerTest(FakeGHL):
    def setUp(self):
        super().setUp()
        self.script = os.path.join(self.tmp, "fake_check.py")
        with open(self.script, "w") as f:
            f.write(FAKE_CHECKER)
        self._old_cc = os.environ.get("HQ_DESK_COPY_CHECK")
        os.environ["HQ_DESK_COPY_CHECK"] = self.script

    def tearDown(self):
        if self._old_cc is None:
            os.environ.pop("HQ_DESK_COPY_CHECK", None)
        else:
            os.environ["HQ_DESK_COPY_CHECK"] = self._old_cc
        super().tearDown()

    def test_uses_the_real_checker_contract(self):
        self.assertEqual(drafts.copy_check("fine", "prospect_sms"), {"status": "ok", "issues": [], "checker": "copy_check"})
        self.assertEqual(drafts.copy_check("BAD", "prospect_sms")["status"], "blocked")
        self.assertEqual(drafts.copy_check("meh", "prospect_email")["status"], "warn")

    def test_merge_reports_held(self):
        desk = self.desk()
        ids = {l["code"]: l["id"] for l in desk["items"]}
        desk, report, held = drafts.merge(desk, {
            ids["41"]: {"sms": "BAD text"},
            ids["E24"]: {"email_subject": "Open beds", "email": "meh body", "action": "Reply today."},
            "not-a-lead": {"sms": "x"},
            "_comment": "ignored",
        })
        self.assertEqual(held, 1)
        self.assertTrue(any(r.startswith("HELD 41 text") for r in report))
        self.assertTrue(any(r.startswith("warn E24 email") for r in report))
        self.assertTrue(any("not-a-lead" in r for r in report))
        e24 = next(l for l in desk["items"] if l["code"] == "E24")
        self.assertEqual(e24["drafts"]["email"]["subject"], "Open beds")
        self.assertEqual(e24["drafts"]["action"], "Reply today.")


if __name__ == "__main__":
    unittest.main()
