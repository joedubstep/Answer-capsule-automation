import json
import os
import re
import unittest

from tools.time_ledger import classify as K
from tools.time_ledger import common as C
from tools.time_ledger import lexicon as L

SYNTH = [
    ("Sales", "Outreach", "no", ["Make reactivation calls", "Call the new lead back", "Dial the old leads list",
                                  "Reactivation calls for the price raise", "Follow up call with a lead",
                                  "Call two leads from the campaign", "Ask Pat about the lead list"]),
    ("Offer work", "Offer", "no", ["Edit the offer doc", "Write the guarantee terms", "Pick the bonus names",
                                   "Trim the offer doc bonus section", "Draft the guarantee metaphor",
                                   "Review the offer doc timeline", "Send Pat the offer doc"]),
    ("CTO", "Tools", "yes", ["Send a prompt to fix the agent", "Clean the Claude sidebar", "Check the Claude chat",
                             "Send Claude a prompt about the dashboard", "Set up the new Claude skill",
                             "Prompt Claude to fix the routine", "Ask Pat in the Claude chat"]),
    ("Admin", "Admin", "no", ["Check email", "Quick email check", "Check email and calendar", "Reply to an email",
                              "Check email for spam", "Finish checking email", "Email Pat back"]),
    ("Personal", "Distraction", "no", ["Reels", "Scroll reels", "Hinge", "Snapchat spotlight", "Got distracted on reels",
                                       "Reels again", "Text Pat on Hinge"]),
]


def synth_rows():
    out = []
    for role, kind, ai, texts in SYNTH:
        for i, t in enumerate(texts):
            out.append({"action": t, "role": role, "kind": kind, "task": role + " task", "ai": ai,
                        "day": "2026-10-%02d" % (10 + i), "timing": "wispr"})
    return out


class ShippedModelTests(unittest.TestCase):
    def setUp(self):
        self.m = K.load_model()

    def test_shape_and_cv_reported(self):
        self.assertEqual(set(self.m["targets"]), set(K.TARGETS))
        for t in K.TARGETS:
            cv = self.m["cv"][t]
            self.assertGreater(cv["accuracy"], cv["majority_baseline"])
            self.assertGreaterEqual(cv["folds"], 5)
        self.assertEqual(self.m["targets"]["role"]["classes"], C.ROLES)

    def test_privacy_of_shipped_model(self):
        with open(C.MODEL_PATH, encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("Example", raw)
        self.assertNotRegex(raw, r"@|https?://|\d{3}[-.]\d{3}[-.]\d{4}")
        m = json.loads(raw)
        for t in m["targets"].values():
            for feat in t["vocab"]:
                self.assertRegex(feat, r"^[a-z0-9_]+$")
            self.assertGreaterEqual(m["min_df"], 3)
        self.assertEqual(K.check_privacy(m), [])

    def test_predictions(self):
        self.assertEqual(K.predict_text("check email")["role"], "Admin")
        self.assertEqual(K.predict_text("send a prompt to Claude to fix the routine")["ai"], True)
        self.assertEqual(K.predict_text("made four reactivation calls to old leads")["role"], "Sales")
        self.assertEqual(K.predict_text("edit the offer doc and choose bonus names")["role"], "Offer work")

    def test_label_row_rules(self):
        r = K.label_row({"type": "blank", "action_text": ""})
        self.assertEqual((r["role"], r["kind"], r["needs_label"]), (C.NOT_LOGGED, C.NOT_LOGGED, False))
        r = K.label_row({"type": "break", "action_text": "stopping work"})
        self.assertEqual((r["role"], r["task"]), (C.NOT_LOGGED, C.BREAK_TASK))
        r = K.label_row({"type": "action", "action_text": "scroll the phone for 15 minutes"})
        self.assertEqual((r["role"], r["kind"], r["labeled_by"]), ("Personal", "Distraction", "rule"))
        r = K.label_row({"type": "action", "action_text": "send prompt to transcribe a reel"})
        self.assertNotEqual(r["labeled_by"], "rule")

    def test_low_confidence_goes_to_claude(self):
        r = K.label_row({"type": "action", "action_text": "figure out the thing with the stuff"})
        self.assertTrue(r["needs_label"])
        self.assertLess(r["confidence"], K.ROUTE_THRESHOLD)
        self.assertEqual(len(r["role_top3"]), 3)


class TrainingTests(unittest.TestCase):
    def test_names_filtered_and_rare_tokens_dropped(self):
        rows = synth_rows()
        banned = K.proper_stems([r["action"] for r in rows])
        self.assertIn("pat", banned)
        self.assertNotIn("claude", banned)                 # allowed tool name
        logs = []
        m = K.train(rows, extra_names=["Robin"], k=3, log=logs.append)
        vocab = set(m["targets"]["role"]["vocab"])
        self.assertNotIn("pat", vocab)
        self.assertFalse([f for f in vocab if "pat" in f.split("_")])
        self.assertIn("claude", vocab)
        self.assertIn("reel", vocab)
        self.assertNotIn("dashboard", vocab)               # in fewer than 3 rows
        self.assertEqual(K.check_privacy(m, banned), [])
        self.assertEqual(len(logs), 4)
        self.assertTrue(all(re.search(r"cv accuracy", x) for x in logs))
        self.assertGreater(m["cv"]["role"]["accuracy"], 0.6)

    def test_lexicon_has_no_known_name_words(self):
        words = {w for table in (L.ROLE, L.KIND, L.AI) for phrases in table.values() for p in phrases
                 for w in p.split()}
        for bad in ("astra", "girl", "missionaries", "scripture"):
            self.assertNotIn(bad, words)

    def test_lexicon_has_no_capitalized_names(self):
        for table in (L.ROLE, L.KIND, L.AI):
            for phrases in table.values():
                for p in phrases:
                    self.assertEqual(p, p.lower())

    def test_hr_can_win_by_lexicon(self):
        self.assertEqual(K.predict_text("interview a candidate for the new hire job post")["role"], "HR and hiring")


if __name__ == "__main__":
    unittest.main()
