import importlib
import json
import os
import shutil
import tempfile
import unittest

from tools.call_engine import rules

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
RID = "900000009"
META = {"title": "joey x Pat Example", "date": "2026-10-29", "recording_id": RID,
        "url": "https://fathom.video/calls/111111111", "kind": "discovery", "type": "Discovery"}


def good_review():
    scores = {i: {"result": "pass", "note": "ok", "ts": "03:20"} for i, _ in rules.RUBRIC_ITEMS}
    scores["X1"] = {"result": "miss", "note": "two made-up client lines", "ts": "04:30"}
    scores["S8"] = {"result": "miss", "note": "no capacity screen", "ts": None}
    return {
        "type": "Discovery", "with": "Pat (Maple Example House)", "outcome": "Interested, wants to talk to his wife.",
        "scores": scores,
        "flags_review": {"1": {"status": "confirmed"}, "2": {"status": "confirmed"}},
        "objections": [{"ts": "08:40", "objection": "Needs to talk to his wife.", "handling": "Validated, offered a PDF.",
                        "verdict": "partial"}],
        "owed": [{"item": "PDF of the plan", "due": "2026-10-30", "ts": "08:52"}],
        "next_step": {"what": "Follow-up call with Pat and his wife", "when": "2026-11-05 10:00"},
        "fix_next_time": ["Say market benchmark, never a client story.", "Ask the capacity question before the doc."],
        "did_well": ["Asked how long the beds were empty at 03:20."],
        "listen_for": [{"ts": "04:30", "label": "made-up client story"}, {"ts": "08:15", "label": "price"}],
        "email": {"to": "pat@example.com", "subject": "Our call today",
                  "body": "Hi Pat,\n\nThanks for the time today. Two rooms open and the agents are slow.\n\n"
                          "I owe you the plan as a PDF. It will be in your inbox tomorrow.\n\n"
                          "We set a call for Thursday at 10 with you and your wife.\n\nJoey"},
    }


class ReviewBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="call_engine_review_")
        self._old = os.environ.get("CALL_ENGINE_DIR")
        os.environ["CALL_ENGINE_DIR"] = self.tmp
        from tools.call_engine import review
        self.rv = importlib.reload(review)
        with open(os.path.join(FIX, "transcript_synthetic.txt"), encoding="utf-8") as f:
            pk = self.rv.build_packet(RID, f.read(), META)
        self.rv._write_json(os.path.join(self.tmp, RID, "packet.json"), pk)
        self.packet = pk

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CALL_ENGINE_DIR", None)
        else:
            os.environ["CALL_ENGINE_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_review(self, obj):
        self.rv._write_json(os.path.join(self.tmp, RID, "review.json"), obj)

    def load(self, name):
        with open(os.path.join(self.tmp, RID, name), encoding="utf-8") as f:
            return json.load(f) if name.endswith(".json") else f.read()


class PacketTests(ReviewBase):
    def test_packet_numbers_flags(self):
        self.assertEqual([f["n"] for f in self.packet["flags"]], [1, 2, 3, 4, 5])
        view = self.rv.packet_view(self.packet)
        self.assertIn('#1 [top] invented_client at 04:30', view)
        self.assertIn("SCORE THESE ROWS: X1, Q1", view)
        self.assertIn("PROMISES", view)


class RenderSalesTests(ReviewBase):
    def test_render_ok(self):
        self.write_review(good_review())
        code, errs, warns = self.rv.render(RID)
        self.assertEqual((code, errs), (0, []))
        row = self.load("row.json")
        self.assertEqual(set(row["properties"]), {"Call", "Type", "With", "Link", "Listen for", "notes", "Watched",
                                                  "Transcript"})
        self.assertEqual(row["properties"]["Watched"], "__NO__")
        self.assertEqual(row["properties"]["Type"], "Discovery")
        self.assertEqual(row["properties"]["Call"], "Pat (Maple Example House) Discovery 10/29")
        self.assertEqual(row["parent"]["data_source_id"], "3b9e1c3d-79d8-8175-9ec7-000befb007ba")
        self.assertIn("04:30 made-up client story", row["properties"]["Listen for"])
        c = row["content"]
        self.assertTrue(c.startswith('<callout icon="\U0001F534" color="red_bg">'))
        self.assertIn('[04:30](https://fathom.video/calls/111111111?timestamp=270) "One of our first clients was in the '
                      'same spot, and they got sixteen tours in thirty days."', c)
        self.assertIn("TOP SEVERITY: made-up client story or result (2)", c)
        self.assertIn("- [ ] PDF of the plan. Due Fri 10/30.", c)
        self.assertIn("(18 of 20 passed)", c)
        self.assertIn("[04:30](https://fathom.video/calls/111111111?timestamp=270) made-up client story", c)
        draft = self.load("draft.json")
        self.assertEqual(draft["to"], ["pat@example.com"])
        self.assertTrue(draft["body"].rstrip().endswith("Joey"))
        res = self.load("result.json")
        self.assertEqual(res["top_flags"], 2)
        self.assertEqual(res["owed"], [{"item": "PDF of the plan", "due": "2026-10-30"}])

    def test_missing_scores_and_unreviewed_top_flag(self):
        rv = good_review()
        del rv["scores"]["S5"]
        rv["flags_review"] = {"1": {"status": "confirmed"}}
        rv["fix_next_time"] = []
        self.write_review(rv)
        code, errs, _ = self.rv.render(RID)
        self.assertEqual(code, 1)
        joined = " | ".join(errs)
        self.assertIn("scores.S5", joined)
        self.assertIn("flag #2 is top severity", joined)
        self.assertIn("fix_next_time needs 1 to 3", joined)

    def test_clear_needs_why_and_shows_in_notes(self):
        rv = good_review()
        rv["flags_review"]["2"] = {"status": "cleared"}
        self.write_review(rv)
        self.assertIn("flag #2 cleared without a why", " ".join(self.rv.render(RID)[1]))
        rv["flags_review"]["2"] = {"status": "cleared", "why": "describes the offer page, checked by listening"}
        self.write_review(rv)
        self.assertEqual(self.rv.render(RID)[0], 0)
        c = self.load("row.json")["content"]
        self.assertIn("TOP SEVERITY: made-up client story or result (1)", c)
        self.assertIn("Cleared flag at 05:12", c)

    def test_email_copy_check_blocks(self):
        rv = good_review()
        rv["email"]["body"] = ("Hi Pat \u2014 thanks. Our clients see 20 tours and it is $2,000 for 90 days.\n\nCheers")
        self.write_review(rv)
        code, errs, _ = self.rv.render(RID)
        self.assertEqual(code, 1)
        joined = " | ".join(errs)
        self.assertIn("dash", joined)
        self.assertIn("price_before_call", joined)
        self.assertIn("invented_results", joined)
        self.assertIn("sign-off", joined)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, RID, "draft.json")))

    def test_skip_email(self):
        rv = good_review()
        rv.pop("email")
        rv["skip_email"] = "Joey already emailed on 10/30"
        self.write_review(rv)
        self.assertEqual(self.rv.render(RID)[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, RID, "draft.json")))
        self.assertFalse(self.load("result.json")["draft"])

    def test_extra_flag_from_listening(self):
        rv = good_review()
        rv["extra_flags"] = [{"rule": "invented_client", "ts": "06:00", "quote": "We did this for a home in your state."}]
        self.write_review(rv)
        self.assertEqual(self.rv.render(RID)[0], 0)
        self.assertIn("(3)", self.load("row.json")["content"])
        self.assertEqual(self.load("result.json")["top_flags"], 3)


class CoachingTests(ReviewBase):
    def test_coaching_row(self):
        tk = ["Ask how long before you pitch.", "Validate, then answer.", "Deposit for a logistical stack.",
              "Stop after the price.", "Book the next call on the call."]
        self.write_review({"kind": "coaching", "with": "Sales coach group", "takeaways": tk,
                           "listen_for": [{"ts": "03:20", "label": "role play"}]})
        self.assertEqual(self.rv.render(RID)[0], 0)
        row = self.load("ls_row.json")
        self.assertEqual(row["properties"]["Type"], "Coaching")
        self.assertEqual(row["properties"]["Watched"], "__NO__")
        self.assertEqual(row["parent"]["data_source_id"], "87165ea0-2b8e-4683-a1d6-488582afca64")
        self.assertIn("5. Book the next call on the call.", row["content"])
        self.write_review({"kind": "coaching", "takeaways": tk[:4]})
        self.assertIn("exactly 5", " ".join(self.rv.render(RID)[1]))


class FinishTests(ReviewBase):
    def test_finish_lines(self):
        self.assertEqual(self.rv.finish()[0], "Call Review: nothing new.")
        self.write_review(good_review())
        self.rv.render(RID)
        line, sms = self.rv.finish(created={RID: {"row": "https://app.notion.com/p/x", "draft": "d1"}})
        self.assertIn("1 sales call(s) reviewed, 1 row(s) added, 1 follow-up draft(s) in Gmail", line)
        self.assertIn("you owe PDF of the plan by Fri 10/30", line)
        self.assertIn("2 made-up client claim(s) flagged", sms)
        self.assertTrue(sms.endswith("Follow-up draft in Gmail."))
        self.assertIsNone(self.rv.finish(created={})[1])            # nothing written, no text
        dry, none = self.rv.finish(dry_run=True)
        self.assertTrue(dry.startswith("Call Review: dry run, nothing written."))
        self.assertIsNone(none)

    def test_finish_reports_held_and_waiting(self):
        new = {"todo": [{"recording_id": "123", "date": "2026-10-30", "title": "Robin discovery"}], "waiting": 2}
        line = self.rv.finish(new_doc=new)[0]
        self.assertIn("0 calls reviewed. Held, not written: 2026-10-30 Robin discovery.", line)
        self.assertIn('2 more waiting; say "run it again".', line)


class LookupTests(unittest.TestCase):
    def test_lookup_reads_fake_ghl(self):
        old = os.environ.get("GHL_FAKE_DIR")
        os.environ["GHL_FAKE_DIR"] = os.path.join(FIX, "ghl")
        try:
            from tools.call_engine import review
            r = review.lookup(name="Pat Example")
            self.assertEqual(r["status"], "ok")
            self.assertEqual(r["contacts"][0]["email"], "pat@example.com")
            self.assertEqual(review.lookup(name="P")["contacts"], [])
        finally:
            if old is None:
                os.environ.pop("GHL_FAKE_DIR", None)
            else:
                os.environ["GHL_FAKE_DIR"] = old


if __name__ == "__main__":
    unittest.main()
