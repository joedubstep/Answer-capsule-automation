import datetime as dt
import json
import os
import unittest

from tools.call_engine import transcript as tr

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
URL = "https://fathom.video/calls/111111111"


def load():
    with open(os.path.join(FIX, "transcript_synthetic.txt"), encoding="utf-8") as f:
        return f.read()


class ParseTests(unittest.TestCase):
    def test_turns_links_and_continuation(self):
        turns = tr.parse(load())
        self.assertEqual(len(turns), 39)
        self.assertEqual(turns[0]["speaker"], "Joey Host")
        self.assertEqual(turns[0]["url"], URL + "?timestamp=2")
        cont = next(t for t in turns if t["ts"] == "05:12")
        self.assertIn("lookalike system", cont["text"])          # the untimed line joined the turn above

    def test_short_form_gets_links_from_url(self):
        text = "[00:03] Joey Host: Hi there.\n[00:07] Pat Example: Hello."
        turns = tr.parse(text, base_url=URL + "?foo=1")
        self.assertEqual(turns[1]["url"], URL + "?timestamp=7")

    def test_hours_timestamps(self):
        text = "[59:58](%s?timestamp=3598) Joey Host: Almost done.\n[1:02:03](%s?timestamp=3723) Pat Example: Bye." % (URL, URL)
        turns = tr.parse(text)
        self.assertEqual(turns[1]["t"], 3723)
        self.assertEqual(turns[1]["ts"], "1:02:03")
        self.assertEqual(tr.fmt_ts(3723), "1:02:03")

    def test_host_detection(self):
        turns = tr.parse(load())
        self.assertEqual(tr.find_host(turns), "Joey Host")
        self.assertEqual(tr.find_host(turns, "joey host"), "Joey Host")
        self.assertIsNone(tr.find_host(turns, "Nobody"))

    def test_empty(self):
        a = tr.analyze("no timestamps here")
        self.assertEqual(a["turns"], 0)
        self.assertIn("error", a)


class AnalyzeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = tr.analyze(load(), call_date="2026-10-29")

    def test_talk_ratio(self):
        r = self.a["talk_ratio"]
        self.assertAlmostEqual(sum(v["pct_words"] for v in r.values()), 100.0, delta=0.2)
        self.assertGreater(r["Joey Host"]["pct_words"], r["Pat Example"]["pct_words"])

    def test_longest_monologue(self):
        lm = self.a["host_longest_monologue"]
        self.assertEqual(lm["ts"], "05:12")
        self.assertEqual(lm["seconds"], 470 - 312)
        self.assertTrue(lm["url"].endswith("timestamp=312"))

    def test_questions_and_price(self):
        self.assertGreaterEqual(self.a["host_questions"], 10)
        self.assertEqual(self.a["first_price"]["ts"], "08:15")     # 08:08 restates their rent; not our price
        self.assertEqual(self.a["first_price_ask"]["ts"], "08:04")
        self.assertEqual(self.a["pitch_start"]["ts"], "05:00")      # screen share

    def test_flags_are_verbatim_with_links(self):
        leads = [f for f in self.a["flags"] if f["rule"] == "leads_for_families"]
        self.assertEqual([f["ts"] for f in leads], ["04:44"])
        self.assertEqual(leads[0]["quote"], "We get you more leads every week and it is the only thing we do.")
        self.assertEqual(leads[0]["url"], URL + "?timestamp=284")
        banned = next(f for f in self.a["flags"] if f["rule"] == "banned_name")
        self.assertEqual(banned["quote"], "The scripts are based on what works for our clients, and the virtual front "
                                          "desk answers every new family for you.")   # the untimed line, word for word
        self.assertEqual(banned["url"], URL + "?timestamp=312")
        # sorted most severe first, then by time: the medium flag at 05:12 comes before the low one at 04:44
        self.assertEqual([(f["severity"], f["ts"]) for f in self.a["flags"]],
                         [("high", "00:09"), ("medium", "05:12"), ("low", "04:44")])

    def test_other_flags(self):
        rules = {(f["rule"], f["ts"]) for f in self.a["flags"]}
        self.assertIn(("good_time_ask", "00:09"), rules)
        self.assertIn(("leads_for_families", "04:44"), rules)
        self.assertIn(("banned_name", "05:12"), rules)
        guest = {t["ts"] for t in tr.parse(load()) if t["speaker"] != "Joey Host"}
        self.assertIn("03:35", guest)                                # Pat says "junk leads" there
        self.assertFalse(any(f["ts"] in guest for f in self.a["flags"]))   # only Joey's lines are flagged

    def test_moves(self):
        mv = self.a["moves"]
        self.assertEqual(mv["timeline"]["first"]["ts"], "03:20")
        self.assertEqual(mv["tried"]["first"]["ts"], "03:31")
        self.assertEqual(mv["commitment"]["first"]["ts"], "04:15")
        self.assertEqual(mv["any_questions"]["count"], 3)
        self.assertEqual(mv["deposit"]["count"], 0)
        self.assertEqual(mv["next_step"]["first"]["ts"], "09:06")
        self.assertEqual(self.a["rapport_minutes"], 2.8)

    def test_promises_and_due_dates(self):
        pr = {p["ts"]: p for p in self.a["promises"]}
        self.assertNotIn("05:00", pr)                               # "share my screen" is not an owed item
        self.assertEqual(pr["08:52"]["due"], "2026-10-30")          # "tomorrow"
        self.assertEqual(pr["09:16"]["due"], "2026-11-05")          # "Thursday" after a Thursday call -> next week

    def test_objections(self):
        kinds = {(o["ts"], o["kind"]) for o in self.a["objection_candidates"]}
        self.assertIn(("08:40", "partner"), kinds)
        self.assertIn(("08:40", "send_info"), kinds)
        self.assertIn(("03:35", "burned"), kinds)
        partner = next(o for o in self.a["objection_candidates"] if o["kind"] == "partner")
        self.assertEqual(partner["reply"]["ts"], "08:52")

    def test_auto_checks(self):
        c = {x["id"]: x["result"] for x in self.a["auto_checks"]}
        self.assertNotIn("X1", c)
        self.assertEqual(c["S1"], "miss")
        self.assertEqual(c["S3"], "pass")
        self.assertEqual(c["S8"], "miss")
        self.assertEqual(c["S10"], "partial")                       # only asked after the pitch
        self.assertEqual(c["S12"], "pass")
        self.assertEqual(c["S15"], "partial")

    def test_frame_is_not_a_close(self):
        text = ("[00:10](%s?timestamp=10) Joey Host: If it fits, we'll go ahead and get you started.\n"
                "[00:20](%s?timestamp=20) Pat Example: Okay.\n"
                "[05:00](%s?timestamp=300) Joey Host: I'm going to share my screen now.\n"
                "[05:10](%s?timestamp=310) Pat Example: I see it.\n" % (URL, URL, URL, URL))
        a = tr.analyze(text)
        s15 = next(x for x in a["auto_checks"] if x["id"] == "S15")
        self.assertEqual(s15["result"], "miss")

    def test_deadline_mismatch(self):
        text = ("[00:10](%s?timestamp=10) Joey Host: The original price ends November 16th.\n"
                "[00:20](%s?timestamp=20) Pat Example: Okay.\n"
                "[00:30](%s?timestamp=30) Joey Host: Prices go up on the 19th.\n"
                "[00:40](%s?timestamp=40) Joey Host: We spoke on the 16th about your rooms.\n" % (URL, URL, URL, URL))
        a = tr.analyze(text, deadline="2026-11-18")
        hits = [f for f in a["flags"] if f["rule"] == "deadline_mismatch"]
        self.assertEqual([h["ts"] for h in hits], ["00:10"])        # the 19th is the day after: fine; no urgency on 00:40
        self.assertIn("Wednesday Nov 18", hits[0]["fix"])
        self.assertEqual(tr.analyze(text)["flags"], [])               # no deadline given, no check
        plain = ("[00:10](%s?timestamp=10) Joey Host: For the 2 beds, the price would cover the full 90 days.\n"
                 "[00:20](%s?timestamp=20) Joey Host: The price goes up after Nov 16.\n" % (URL, URL))
        hits = [f for f in tr.analyze(plain, deadline="2026-11-18")["flags"] if f["rule"] == "deadline_mismatch"]
        self.assertEqual([h["ts"] for h in hits], ["00:20"])         # "the 2 beds" is not a date

    def test_client_stories_are_not_flagged(self):
        lines = ["We've worked with a home just like yours.", "Most of our clients get 20 tours.",
                 "That is a total of 900k of client ad spend.", "It is already proven on other care homes.",
                 "I can send you our case studies.", "We haven't had anyone get less than ten."]
        for i, line in enumerate(lines):
            text = "[00:%02d](%s?timestamp=%d) Joey Host: %s" % (i, URL, i, line)
            self.assertEqual(tr.analyze(text)["flags"], [], line)

    def test_json_wrapped_result(self):
        body = "[00:01](%s?timestamp=1) Joey Host: Tell me about your home.\n[00:05](%s?timestamp=5) Pat Example: Ten beds." % (URL, URL)
        for wrapped in (json.dumps([{"type": "text", "text": body}]), json.dumps({"result": body})):
            a = tr.analyze(wrapped)
            self.assertEqual((a["turns"], a["host"]), (2, "Joey Host"))

    def test_due_from(self):
        fri = dt.date(2026, 10, 30)
        self.assertEqual(tr.due_from("I'll send it over.", fri)[0], dt.date(2026, 11, 2))   # next business day
        self.assertEqual(tr.due_from("I'll send it today.", fri)[0], fri)
        self.assertEqual(tr.due_from("I'll call you next week.", fri)[0], dt.date(2026, 11, 2))
        self.assertEqual(tr.due_from("I'll send it Monday.", fri)[0], dt.date(2026, 11, 2))
        self.assertEqual(tr.due_from("x", None), (None, "no call date"))

    def test_summary_has_no_quotes(self):
        s = tr.summary(self.a)
        self.assertIn("first price (host): 08:15", s)
        self.assertNotIn("sixteen tours", s)


if __name__ == "__main__":
    unittest.main()
