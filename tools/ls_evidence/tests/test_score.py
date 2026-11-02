"""The whole pipeline on the synthetic fixtures: pull through the GHL_FAKE_DIR hook, then score."""
import datetime as dt

from tools.ls_evidence import score as S
from tools.ls_evidence.tests import fixtures as fx
from tools.ls_evidence.tests.base import FakeGHL


class EvidenceTest(FakeGHL):
    def setUp(self):
        super().setUp()
        self.ev = self.evidence()
        self.L = self.leads(self.ev)
        self.C = self.calls(self.ev)

    def test_lead_answers_in_portal_order(self):
        want = {"Pat": "YY-YYN", "Sam": "YNY--Y", "Lee": "YY-NYN", "Alex": "YN-NNN", "Robin": "NYN--Y",
                "Casey": "YYY--Y", "Taylor": "Y----Y", "Jordan": "-----N"}
        self.assertEqual({k: self.L[k]["answers"] for k in want}, want)

    def test_left_out(self):
        self.assertNotIn("Drew", self.L)          # test tag
        self.assertNotIn("Morgan", self.L)        # before ads went live
        self.assertNotIn("Noah", self.L)          # not a Lead Suite lead
        self.assertTrue(self.L["Kim"]["duplicate"])
        self.assertEqual(self.ev["excluded"], {"test": 1, "before_live": 1, "duplicate": 1, "not_read": 0})

    def test_lead_in_sources(self):
        self.assertEqual(self.L["Alex"]["t0_src"], "STL Lead In At")
        self.assertEqual(self.L["Alex"]["t0_et"], "Thu Oct 22, 9am")
        self.assertIn("came back", self.L["Robin"]["t0_src"])
        self.assertEqual(self.L["Robin"]["t0_et"], "Mon Oct 26, 10am")
        self.assertEqual(self.L["Pat"]["t0_src"], "contact created")

    def test_dst_night_lead(self):
        lee = self.L["Lee"]
        self.assertTrue(lee["after_hours"])
        self.assertEqual(lee["t0_et"], "Sat Oct 31, 11:30pm")
        self.assertIn("clock started Sun Nov 1, 8am ET", lee["boxes"]["triple_dial"]["why"])
        # 10:30am EST is before the SMS 2 window (11am to 12pm). An EDT mistake would have called it on time.
        self.assertEqual(lee["boxes"]["sms2"]["a"], S.NO)
        self.assertIn("no text Sun Nov 1, 11am to 12pm", lee["boxes"]["sms2"]["why"])
        self.assertEqual(lee["boxes"]["sms3"]["a"], S.YES)

    def test_field_wins_with_check(self):
        alex = self.L["Alex"]
        self.assertEqual(alex["boxes"]["triple_dial"]["src"], "field")
        self.assertEqual(len(alex["checks"]), 1)
        self.assertIn("GHL field says Yes", alex["checks"][0])
        self.assertEqual(alex["field_count"], 2)

    def test_missed_call_in_needs_double_dial(self):
        r = self.L["Robin"]["boxes"]
        self.assertEqual(r["double_dial"]["a"], S.NO)
        self.assertIn("call to us (missed)", r["double_dial"]["why"])
        self.assertIn("2 dials in the first 5 min", r["triple_dial"]["why"])

    def test_auto_dial_length_from_transcript(self):
        t = self.L["Taylor"]["boxes"]
        self.assertIn("dial 1 was answered", t["triple_dial"]["why"])
        self.assertEqual(self.C["Taylor"]["boxes"]["triage"]["a"], S.YES)
        self.assertIn("talked 2 min", self.C["Taylor"]["boxes"]["triage"]["why"])      # 200 words / 1.8 = 111 s

    def test_calls(self):
        want = {"Sam": "YYYYY", "Robin": "NNNN?", "Taylor": "YNNYN"}
        self.assertEqual({k: self.C[k]["answers"] for k in want}, want)
        self.assertEqual(set(self.C), {"Sam", "Robin", "Taylor", "Casey"})   # copies, client and coaching calls dropped
        moved = self.calls(self.ev, "moved")
        self.assertEqual(list(moved), ["Casey"])
        self.assertEqual(self.C["Casey"]["start_et"], "Tue Nov 10, 10am")

    def test_central_lead_precall_email(self):
        b = self.C["Taylor"]["boxes"]["precall_email"]
        self.assertEqual(b["a"], S.NO)       # 4:30pm Central on Sun Nov 1 is before the evening
        self.assertIn("(from 5pm Central time)", b["why"])
        self.assertEqual(self.C["Taylor"]["boxes"]["morning_confirm"]["a"], S.YES)

    def test_counts(self):
        self.assertTrue(self.C["Sam"]["counts"])
        self.assertTrue(self.C["Taylor"]["counts"])
        self.assertTrue(self.C["Casey"]["counts"])
        self.assertFalse(self.C["Robin"]["counts"])
        self.assertIn("Wrong Fit", self.C["Robin"]["count_why"])

    def test_notes_stub_never_invented(self):
        n = self.C["Sam"]["notes"]
        self.assertTrue(n["src"].startswith("GHL note"))
        self.assertTrue(n["text"].startswith("OUTCOME: Talked 30 min."))
        self.assertNotIn("Extra sentence", n["text"])          # 5 sentences at most
        self.assertNotIn("555", n["text"])
        self.assertEqual(self.C["Robin"]["notes"]["src"], "meeting brief, written before the call")
        self.assertEqual(self.C["Casey"]["notes"], {"src": "", "text": ""})

    def test_scoreboard(self):
        b = self.ev["scoreboard"]
        self.assertEqual((b["qualified_booked"], b["booked_in_window"], b["unqualified"], b["held"], b["upcoming"]),
                         (3, 4, 1, 1, 1))
        self.assertEqual((self.ev["window"]["used"], self.ev["window"]["left"]), (82, 8))
        self.assertEqual(b["leads"], 8)
        self.assertEqual(b["leads_booked"], 3)

    def test_sop_rate(self):
        self.assertEqual(self.ev["sop"]["leads"], {"yes": 15, "no": 7, "pct": 68})
        self.assertEqual(self.ev["sop"]["calls"], {"yes": 7, "no": 6, "pct": 54})
        self.assertEqual(self.ev["sop"]["all"], {"yes": 22, "no": 13, "pct": 63})

    def test_field_report(self):
        fr = self.ev["field_report"]
        self.assertEqual(fr["missing"], [])
        self.assertEqual(fr["leads_with_any"], 1)
        self.assertEqual(fr["how"]["sms1"], "key")


class PortalTest(FakeGHL):
    def test_first_run_lists_every_finished_row(self):
        p = self.evidence()["portal"]
        self.assertTrue(p["first_run"])
        self.assertEqual(len(p["new_leads"]), 7)         # Jordan is still inside his windows
        self.assertEqual(len(p["waiting_leads"]), 1)
        self.assertEqual(len(p["new_calls"]), 3)         # Casey's call is ahead
        self.assertEqual(len(p["waiting_calls"]), 1)

    def test_next_week_lists_only_new_rows(self):
        ev = self.evidence()
        nxt = self.evidence(now=fx.NOW + dt.timedelta(days=7), prev=ev["state"])
        p = nxt["portal"]
        self.assertFalse(p["first_run"])
        L = {r["hash"]: r["first"] for r in nxt["leads"]}
        C = {r["hash"]: r["first"] for r in nxt["calls"]}
        self.assertEqual([L[h] for h in p["new_leads"]], ["Jordan"])      # finished during the week
        # Casey's call is now past. It has no outcome yet, so it is listed with Showed unknown.
        self.assertEqual([C[h] for h in p["new_calls"]], ["Casey"])
        self.assertEqual(p["changed_leads"], [])
        self.assertEqual(p["prev_date"], "2026-11-08")

    def test_changed_row_comes_back(self):
        ev = self.evidence()
        state = ev["state"]
        pat = next(r for r in ev["leads"] if r["first"] == "Pat")
        state["rows"]["L" + pat["hash"]] = "YYNYYN"          # as if box 3 had been No when it was listed
        p = self.evidence(prev=state)["portal"]
        self.assertEqual(p["changed_leads"], [{"hash": pat["hash"], "was": "YYNYYN"}])
        self.assertEqual(p["new_leads"], [])

    def test_entered_through(self):
        p = self.evidence(entered_through="2026-10-25")["portal"]
        ev = self.evidence(entered_through="2026-10-25")
        names = {r["hash"]: r["first"] for r in ev["leads"]}
        self.assertEqual(sorted(names[h] for h in p["new_leads"]), ["Casey", "Lee", "Robin", "Taylor"])
        self.assertFalse(p["first_run"])
        self.assertEqual(ev["state"]["entered_through"], "2026-10-25")

    def test_prev_from_another_location_is_ignored(self):
        ev = self.evidence()
        state = dict(ev["state"], loc="somewhere-else")
        self.assertTrue(self.evidence(prev=state)["portal"]["first_run"])


class AnswersChangeTest(FakeGHL):
    """Pat replies a week later: his row comes back as changed."""

    def patch(fs):
        msgs = fs["conversations__vPat__messages.json"]["messages"]["messages"]
        msgs.insert(0, {"id": "p7", "contactId": "cPat00001", "dateAdded": "2026-11-10T15:00:00.000Z",
                        "messageType": "TYPE_SMS", "direction": "inbound", "status": "delivered", "type": 2,
                        "body": "who is this"})

    def test_reply_changes_the_row(self):
        from tools.ls_evidence import profile as prof
        first = S.build(self.raw(), prof.load_settings(), now=fx.NOW)
        pat_hash = next(r["hash"] for r in first["leads"] if r["first"] == "Pat")
        first["state"]["rows"]["L" + pat_hash] = "YY-YYN"
        nxt = self.evidence(now=fx.NOW + dt.timedelta(days=7), prev=first["state"])
        self.assertIn({"hash": pat_hash, "was": "YY-YYN"}, nxt["portal"]["changed_leads"])
        pat = next(r for r in nxt["leads"] if r["first"] == "Pat")
        self.assertEqual(pat["answers"], "YYNYYY")      # the reply makes the double dial due, and none followed
