"""Every box rule, on hand-built message lists (no GHL). Times are UTC; Oct dates are EDT (UTC-4), Nov 1 on are EST."""
import datetime as dt
import unittest

from tools.ls_evidence import profile as prof
from tools.ls_evidence import score as S

UTC = dt.timezone.utc
SOP = prof.load_settings()["sop"]


def T(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


T0 = T("2026-10-19T14:00:00")       # Mon Oct 19, 10:00am EDT
LATE = T("2026-11-20T12:00:00")     # long after everything


def msgs(*specs):
    """specs: (id, iso time, kind, extra dict). kinds: dial, dead, callin, callin_missed, sms, sms_failed, smsin, email,
    emailin, auto."""
    out = []
    for sid, when, kind, *extra in specs:
        x = extra[0] if extra else {}
        m = {"id": sid, "when": when + "Z" if "Z" not in when and "+" not in when else when}
        if kind == "dial":
            m.update(dir="outbound", type="TYPE_CAMPAIGN_CALL", status=x.get("status", "no-answer"))
        elif kind == "dead":
            m.update(dir="outbound", type="TYPE_CAMPAIGN_CALL", status="canceled")
        elif kind == "callin":
            m.update(dir="inbound", type="TYPE_CALL", status="completed")
        elif kind == "callin_missed":
            m.update(dir="inbound", type="TYPE_CALL", status="no-answer")
        elif kind == "sms":
            m.update(dir="outbound", type="TYPE_SMS", status="delivered")
        elif kind == "sms_failed":
            m.update(dir="outbound", type="TYPE_SMS", status="failed")
        elif kind == "smsin":
            m.update(dir="inbound", type="TYPE_SMS", status="delivered")
        elif kind == "email":
            m.update(dir="outbound", type="TYPE_EMAIL", subject=x.get("subject", "SURVEN [REQUIRED-URGENT] Watch"))
        elif kind == "emailin":
            m.update(dir="inbound", type="TYPE_EMAIL")
        elif kind == "auto":
            m.update(dir="inbound", type="TYPE_EMAIL", auto=True)
        if "duration" in x:
            m["duration"] = x["duration"]
        out.append(m)
    return S.norm_msgs({"msgs": out}, {}, SOP)


def lead(ms, t0=T0, now=LATE, zone="eastern", fields=None, ok=True, known_from=None):
    boxes, facts = S.lead_boxes(t0, zone, ms, SOP, now, fields or {}, ok, known_from)
    return boxes


class TripleDialTest(unittest.TestCase):
    def test_three_dials_within_five_minutes(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial"), ("b", "2026-10-19T14:02:00", "dial"),
                      ("c", "2026-10-19T14:05:00", "dial")))["triple_dial"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("3 dials by 10:05am, 5 min after the form", b["why"])

    def test_third_dial_one_second_late_is_no(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial"), ("b", "2026-10-19T14:02:00", "dial"),
                      ("c", "2026-10-19T14:05:01", "dial")))["triple_dial"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("2 dials in the first 5 min", b["why"])

    def test_canceled_bridge_calls_are_not_dials(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dead"), ("b", "2026-10-19T14:02:00", "dead"),
                      ("c", "2026-10-19T14:03:00", "dial")))["triple_dial"]
        self.assertEqual(b["a"], S.NO)

    def test_answered_dial_counts(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial", {"status": "completed", "duration": 120})))["triple_dial"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("dial 1 was answered", b["why"])

    def test_short_answered_dial_is_not_a_talk(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial", {"status": "completed", "duration": 8})))["triple_dial"]
        self.assertEqual(b["a"], S.NO)

    def test_not_due_while_window_open(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial")), now=T("2026-10-19T14:03:00"))["triple_dial"]
        self.assertEqual(b["a"], S.NOT_DUE)
        self.assertTrue(b["pending"])

    def test_first_dial_late(self):
        b = lead(msgs(("a", "2026-10-19T14:47:00", "dial")))["triple_dial"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("first dial 47 min after the form", b["why"])

    def test_after_hours_clock_starts_at_8am_lead_time(self):
        t0 = T("2026-10-20T02:00:00")       # Mon Oct 19, 10pm EDT
        ms = msgs(("a", "2026-10-20T12:01:00", "dial"), ("b", "2026-10-20T12:02:00", "dial"),
                  ("c", "2026-10-20T12:03:00", "dial"))
        b = lead(ms, t0=t0)["triple_dial"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("came in after hours, so the clock started Tue Oct 20, 8am ET", b["why"])

    def test_night_touch_is_measured_from_the_form(self):
        t0 = T("2026-10-20T03:00:00")       # Mon 11pm EDT
        ms = msgs(("s", "2026-10-20T03:01:00", "sms"), ("a", "2026-10-20T12:01:00", "dial"),
                  ("b", "2026-10-20T12:02:00", "dial"), ("c", "2026-10-20T12:03:00", "dial"))
        b = lead(ms, t0=t0)
        self.assertEqual(b["sms1"]["a"], S.YES)
        self.assertIn("text at 11:01pm, 1 min after the form", b["sms1"]["why"])
        self.assertIn("3 dials by 8:03am, 3 min after the form", b["triple_dial"]["why"])
        self.assertNotIn("before it", b["sms1"]["why"] + b["triple_dial"]["why"])

    def test_after_hours_in_central_time(self):
        t0 = T("2026-10-20T00:30:00")       # Mon 8:30pm EDT, but 7:30pm CDT: still open on a Central lead's clock
        ms = msgs(("a", "2026-10-20T00:31:00", "dial"), ("b", "2026-10-20T00:32:00", "dial"),
                  ("c", "2026-10-20T00:33:00", "dial"))
        self.assertEqual(lead(ms, t0=t0, zone="central")["triple_dial"]["a"], S.YES)
        b = lead(ms, t0=T("2026-10-20T02:30:00"), zone="central")      # 9:30pm CDT: next morning 8am CDT = 13:00Z
        self.assertIn("Tue Oct 20, 9am ET", b["triple_dial"]["why"] + b["sms1"]["why"])

    def test_unknown_when_older_messages_missing(self):
        cut = T("2026-10-19T20:00:00")          # only messages from 4pm EDT on were read
        b = lead(msgs(("x", "2026-10-19T20:30:00", "sms")), known_from=cut)
        for k in ("triple_dial", "sms1", "sms2", "lead_replied", "double_dial"):
            self.assertEqual(b[k]["a"], S.UNKNOWN, k)
        self.assertEqual(lead([], ok=False)["triple_dial"]["a"], S.UNKNOWN)
        self.assertEqual(lead([], ok=False)["double_dial"]["a"], S.UNKNOWN)
        # proof found inside the part that was read still counts
        ms = msgs(("a", "2026-10-19T14:01:00", "dial"), ("b", "2026-10-19T14:02:00", "dial"),
                  ("c", "2026-10-19T14:03:00", "dial"))
        self.assertEqual(lead(ms, known_from=T("2026-10-19T14:01:00"))["triple_dial"]["a"], S.YES)

    def test_answered_dial_with_no_length_says_check(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial", {"status": "completed"})))
        self.assertEqual(b["triple_dial"]["a"], S.YES)
        self.assertIn("may have been a voicemail", b["triple_dial"]["check"])
        self.assertEqual(b["sms1"]["a"], S.NOT_DUE)
        self.assertIn("may have been a voicemail", b["sms1"]["check"])

    def test_nine_pm_next_day_rule(self):
        # 8:50pm EDT: before the 9pm cutoff, so the dials were due right away
        ms = msgs(("a", "2026-10-20T12:01:00", "dial"), ("b", "2026-10-20T12:02:00", "dial"),
                  ("c", "2026-10-20T12:03:00", "dial"))
        b = lead(ms, t0=T("2026-10-20T00:50:00"))["triple_dial"]
        self.assertEqual(b["a"], S.NO)
        self.assertNotIn("after hours", b["why"])
        # 9:05pm EDT: next morning at 8am
        b = lead(ms, t0=T("2026-10-20T01:05:00"))["triple_dial"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("clock started Tue Oct 20, 8am ET", b["why"])
        # 6:30am EDT: before opening, so 8am the same day
        ms = msgs(("a", "2026-10-20T12:01:00", "dial"), ("b", "2026-10-20T12:02:00", "dial"),
                  ("c", "2026-10-20T12:04:00", "dial"))
        self.assertEqual(lead(ms, t0=T("2026-10-20T10:30:00"))["triple_dial"]["a"], S.YES)


class Sms1Test(unittest.TestCase):
    def test_text_at_five_minutes_is_yes(self):
        self.assertEqual(lead(msgs(("s", "2026-10-19T14:05:00", "sms")))["sms1"]["a"], S.YES)

    def test_text_at_six_minutes_is_no(self):
        b = lead(msgs(("s", "2026-10-19T14:06:00", "sms")))["sms1"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("first text 6 min after the form", b["why"])

    def test_failed_text_does_not_count(self):
        self.assertEqual(lead(msgs(("s", "2026-10-19T14:02:00", "sms_failed")))["sms1"]["a"], S.NO)

    def test_not_due_when_they_talked_first(self):
        b = lead(msgs(("a", "2026-10-19T14:01:00", "dial", {"status": "completed", "duration": 200})))["sms1"]
        self.assertEqual(b["a"], S.NOT_DUE)


class DoubleDialTest(unittest.TestCase):
    def test_two_dials_after_reply(self):
        b = lead(msgs(("r", "2026-10-19T15:00:00", "smsin"), ("a", "2026-10-19T15:02:00", "dial"),
                      ("b", "2026-10-19T15:04:00", "dial")))["double_dial"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("2 dials within 4 min of the text", b["why"])

    def test_one_dial_is_no(self):
        b = lead(msgs(("r", "2026-10-19T15:00:00", "smsin"), ("a", "2026-10-19T15:02:00", "dial"),
                      ("b", "2026-10-19T15:30:00", "dial")))["double_dial"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("1 dial in the 10 min after the text", b["why"])

    def test_answered_call_back_is_yes(self):
        b = lead(msgs(("r", "2026-10-19T15:00:00", "smsin"),
                      ("a", "2026-10-19T15:01:00", "dial", {"status": "completed", "duration": 90})))["double_dial"]
        self.assertEqual(b["a"], S.YES)

    def test_no_reply_is_not_due(self):
        self.assertEqual(lead([])["double_dial"]["a"], S.NOT_DUE)
        self.assertFalse(lead([])["double_dial"]["pending"])

    def test_missed_call_from_them_needs_a_double_dial(self):
        b = lead(msgs(("r", "2026-10-19T15:00:00", "callin_missed")))["double_dial"]
        self.assertEqual(b["a"], S.NO)

    def test_reply_at_night_moves_to_the_morning(self):
        ms = msgs(("r", "2026-10-20T03:00:00", "smsin"),          # 11pm EDT
                  ("a", "2026-10-20T12:02:00", "dial"), ("b", "2026-10-20T12:04:00", "dial"))   # 8:02am, 8:04am
        b = lead(ms)["double_dial"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("(after hours)", b["why"])

    def test_auto_reply_is_not_a_reply(self):
        self.assertEqual(lead(msgs(("r", "2026-10-19T15:00:00", "auto")))["lead_replied"]["a"], S.NO)

    def test_stop_reply_needs_no_double_dial(self):
        ms = S.norm_msgs({"msgs": [{"id": "r", "when": "2026-10-19T15:00:00Z", "dir": "inbound", "type": "TYPE_SMS",
                                    "status": "delivered", "stop": True}]}, {}, SOP)
        b = lead(ms)
        self.assertEqual(b["double_dial"]["a"], S.NOT_DUE)
        self.assertIn("STOP", b["double_dial"]["why"])
        self.assertEqual(b["lead_replied"]["a"], S.YES)

    def test_short_call_in_is_a_reply_not_a_talk(self):
        b = lead(msgs(("r", "2026-10-19T15:00:00", "callin", {"duration": 12})))
        self.assertEqual(b["double_dial"]["a"], S.NO)
        self.assertIn("call to us (short)", b["double_dial"]["why"])


class LadderTest(unittest.TestCase):
    def test_sms2_window_edges(self):
        for when, want in (("2026-10-19T17:00:00", S.YES), ("2026-10-19T18:00:00", S.YES),
                           ("2026-10-19T16:59:00", S.NO), ("2026-10-19T18:01:00", S.NO)):
            b = lead(msgs(("s1", "2026-10-19T14:02:00", "sms"), ("s2", when, "sms")))["sms2"]
            self.assertEqual(b["a"], want, when)

    def test_sms1_is_never_sms2(self):
        # a late SMS 1 that lands in the SMS 2 window is still SMS 1, so SMS 2 is a No
        b = lead(msgs(("s1", "2026-10-19T17:30:00", "sms")))
        self.assertEqual((b["sms1"]["a"], b["sms2"]["a"]), (S.NO, S.NO))
        self.assertIn("first text 3 h 30 min after the form", b["sms1"]["why"])
        b = lead(msgs(("s1", "2026-10-19T17:30:00", "sms"), ("s2", "2026-10-19T17:45:00", "sms")))
        self.assertEqual((b["sms1"]["a"], b["sms2"]["a"]), (S.NO, S.YES))
        b = lead(msgs(("s1", "2026-10-19T14:02:00", "sms")))
        self.assertEqual(b["sms2"]["a"], S.NO)
        self.assertIn("no text Mon Oct 19, 1pm to 2pm", b["sms2"]["why"])

    def test_sms3_follows_sms2(self):
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("s2", "2026-10-19T17:40:00", "sms"),
                  ("s3", "2026-10-19T20:10:00", "sms"))      # 2h30 after SMS 2
        b = lead(ms)
        self.assertEqual((b["sms2"]["a"], b["sms3"]["a"]), (S.YES, S.YES))
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("s2", "2026-10-19T17:40:00", "sms"),
                  ("s3", "2026-10-19T19:30:00", "sms"))      # 1h50: too soon
        self.assertEqual(lead(ms)["sms3"]["a"], S.NO)

    def test_sms3_anchor_when_sms2_missing(self):
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("s3", "2026-10-19T19:30:00", "sms"))   # due 7pm to 8pm UTC
        self.assertEqual(lead(ms)["sms3"]["a"], S.YES)

    def test_texts_stop_after_a_reply(self):
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("r", "2026-10-19T16:00:00", "smsin"))
        b = lead(ms)
        self.assertEqual((b["sms2"]["a"], b["sms3"]["a"]), (S.NOT_DUE, S.NOT_DUE))
        self.assertIn("so the texts stop", b["sms2"]["why"])

    def test_reply_inside_the_window_before_a_text_stops_it(self):
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("r", "2026-10-19T17:20:00", "smsin"))   # 3h20 in, no SMS 2
        b = lead(ms)
        self.assertEqual((b["sms2"]["a"], b["sms3"]["a"]), (S.NOT_DUE, S.NOT_DUE))
        self.assertIn("inside the SMS 2 window and before a text went", b["sms2"]["why"])
        # a reply after the window closed does not excuse a missed SMS 2
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("r", "2026-10-19T18:30:00", "smsin"))
        self.assertEqual(lead(ms)["sms2"]["a"], S.NO)

    def test_reply_after_sms2_stops_only_sms3(self):
        ms = msgs(("s1", "2026-10-19T14:02:00", "sms"), ("s2", "2026-10-19T17:10:00", "sms"),
                  ("r", "2026-10-19T17:30:00", "smsin"))
        b = lead(ms)
        self.assertEqual((b["sms2"]["a"], b["sms3"]["a"]), (S.YES, S.NOT_DUE))

    def test_evening_lead_sms2_moves_past_quiet_hours(self):
        t0 = T("2026-10-19T22:00:00")       # 6pm EDT: SMS 2 due 9pm to 10pm, inside quiet hours, so 8am to 9am
        ms = msgs(("s1", "2026-10-19T22:02:00", "sms"), ("s2", "2026-10-20T12:30:00", "sms"))
        b = lead(ms, t0=t0)["sms2"]
        self.assertEqual(b["a"], S.YES)

    def test_pending_ladder(self):
        b = lead(msgs(("s1", "2026-10-19T14:02:00", "sms")), now=T("2026-10-19T16:00:00"))
        self.assertTrue(b["sms2"]["pending"])
        self.assertTrue(b["sms3"]["pending"])


class FieldTest(unittest.TestCase):
    def test_field_wins_and_disagreement_is_flagged(self):
        b = lead([], fields={"triple_dial": "Yes", "sms1": ["No"], "lead_replied": "yes"})
        self.assertEqual(b["triple_dial"]["a"], S.YES)
        self.assertEqual(b["triple_dial"]["src"], "field")
        self.assertIn("GHL field says Yes, the messages say No", b["triple_dial"]["check"])
        self.assertEqual(b["sms1"]["a"], S.NO)
        self.assertIsNone(b["sms1"]["check"])
        self.assertEqual(b["lead_replied"]["a"], S.YES)

    def test_blank_or_odd_field_falls_back_to_messages(self):
        ms = msgs(("a", "2026-10-19T14:01:00", "dial"), ("b", "2026-10-19T14:02:00", "dial"),
                  ("c", "2026-10-19T14:03:00", "dial"))
        for v in ("", None, [], "maybe"):
            b = lead(ms, fields={"triple_dial": v} if v is not None else {})["triple_dial"]
            self.assertEqual((b["a"], b["src"]), (S.YES, "messages"), repr(v))

    def test_yes_no_shapes(self):
        for v, want in (("Yes", True), (["Yes"], True), ("TRUE", True), (1, True), ("No", False), (["no"], False),
                        ("0", False), ("", None), ("maybe", None), (None, None), ("Showed", True), ("No Show", False)):
            self.assertEqual(S.yes_no(v), want, repr(v))

    def test_lead_in_field_needs_a_time_of_day(self):
        live = T("2026-08-08T04:00:00")
        base = {"dateAdded": "2026-10-19T14:00:00.000Z", "opps": []}
        t, src = S.lead_in(dict(base, fields={"lead_in_at": "2026-10-19"}), live)
        self.assertEqual((t, src), (T0, "contact created"))
        t, src = S.lead_in(dict(base, fields={"lead_in_at": 1760918400000}), live)    # midnight UTC: a date field
        self.assertEqual(src, "contact created")
        t, src = S.lead_in(dict(base, fields={"lead_in_at": "2026-10-19T14:07:00Z"}), live)
        self.assertEqual((t, src), (T("2026-10-19T14:07:00"), "STL Lead In At"))

    def test_returning_contact_uses_the_new_deal(self):
        live = T("2026-08-08T04:00:00")
        t, src = S.lead_in({"dateAdded": "2026-06-01T12:00:00Z", "fields": {},
                            "opps": [{"createdAt": "2026-05-01T00:00:00Z"}, {"createdAt": "2026-10-26T14:00:00Z"}]}, live)
        self.assertEqual(t, T("2026-10-26T14:00:00"))
        self.assertIn("came back", src)


def call(start, booked, status="confirmed", cid="c1"):
    return {"_start": T(start), "_booked": T(booked), "status": status, "contactId": cid}


def cboxes(c, ms, now=LATE, zone="eastern", notes=None, fields=None, stage="", latest=True, t0=T0, stage_at=None):
    return S.call_boxes(c, t0, zone, ms, SOP, now, notes, fields, stage, latest, stage_at=stage_at)


class CallBoxesTest(unittest.TestCase):
    def test_triage(self):
        c = call("2026-10-22T18:00:00", "2026-10-20T15:40:00")
        self.assertEqual(cboxes(c, msgs(("a", "2026-10-20T15:35:00", "dial",
                                         {"status": "completed", "duration": 600})))["triage"]["a"], S.YES)
        b = cboxes(c, msgs(("a", "2026-10-20T15:35:00", "dial", {"status": "completed", "duration": 20})))["triage"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("1 short call under 60 seconds", b["why"])
        b = cboxes(c, msgs(("a", "2026-10-20T15:35:00", "dial", {"status": "completed"})))["triage"]
        self.assertEqual(b["a"], S.YES)
        self.assertEqual(b["check"], "call length is not in GHL")
        self.assertEqual(cboxes(c, msgs(("a", "2026-10-22T18:10:00", "callin")))["triage"]["a"], S.NO)   # after the call

    def test_precall_email_evening_before_across_dst(self):
        # Mon Nov 2, 9am EST call. The evening before is Sun Nov 1 from 5pm EST (22:00 UTC), the day DST ended.
        c = call("2026-11-02T14:00:00", "2026-10-29T15:00:00")
        no = cboxes(c, msgs(("e", "2026-11-01T21:30:00", "email")))["precall_email"]    # 4:30pm EST
        self.assertEqual(no["a"], S.NO)
        self.assertIn("an email went out Sun Nov 1, 4:30pm ET", no["why"])
        self.assertEqual(cboxes(c, msgs(("e", "2026-11-01T22:15:00", "email")))["precall_email"]["a"], S.YES)
        self.assertEqual(cboxes(c, msgs(("e", "2026-11-02T05:30:00", "email")))["precall_email"]["a"], S.NO)  # after midnight

    def test_precall_email_subject_must_match(self):
        c = call("2026-10-22T18:00:00", "2026-10-20T15:40:00")
        self.assertEqual(cboxes(c, msgs(("e", "2026-10-21T22:30:00", "email", {"subject": "Invoice"})))
                         ["precall_email"]["a"], S.NO)
        b = cboxes(c, msgs(("e", "2026-10-21T22:30:00", "email", {"subject": ""})))["precall_email"]
        self.assertEqual((b["a"], b["check"]), (S.YES, "email subject not shown in GHL"))

    def test_booked_after_the_evening_before(self):
        c = call("2026-10-22T18:00:00", "2026-10-22T12:00:00")       # booked the same morning
        self.assertEqual(cboxes(c, [])["precall_email"]["a"], S.NOT_DUE)
        self.assertEqual(cboxes(c, msgs(("e", "2026-10-22T12:05:00", "email")))["precall_email"]["a"], S.YES)

    def test_morning_confirm(self):
        c = call("2026-10-22T18:00:00", "2026-10-20T15:40:00")      # Thu 2pm EDT
        self.assertEqual(cboxes(c, msgs(("m", "2026-10-22T13:00:00", "sms")))["morning_confirm"]["a"], S.YES)
        self.assertEqual(cboxes(c, msgs(("m", "2026-10-22T08:00:00", "sms")))["morning_confirm"]["a"], S.NO)  # 4am
        self.assertEqual(cboxes(c, msgs(("m", "2026-10-22T13:00:00", "dead")))["morning_confirm"]["a"], S.NO)
        # a text at 1pm for a 2pm call is not a morning confirm
        b = cboxes(c, msgs(("m", "2026-10-22T17:00:00", "sms")))["morning_confirm"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("(from 5am to 12pm)", b["why"])
        # a 9am call: the morning ends when the call starts
        c9 = call("2026-10-22T13:00:00", "2026-10-20T15:40:00")
        self.assertEqual(cboxes(c9, msgs(("m", "2026-10-22T12:30:00", "sms")))["morning_confirm"]["a"], S.YES)
        self.assertEqual(cboxes(c9, msgs(("m", "2026-10-22T13:10:00", "sms")))["morning_confirm"]["a"], S.NO)

    def test_same_day_afternoon_booking_has_no_morning(self):
        c = call("2026-10-22T23:00:00", "2026-10-22T20:30:00")      # booked 4:30pm for 7pm
        b = cboxes(c, msgs(("m", "2026-10-22T20:31:00", "sms")))["morning_confirm"]
        self.assertEqual(b["a"], S.NOT_DUE)

    def test_show_sop_needs_all_three(self):
        c = call("2026-10-22T18:00:00", "2026-10-20T15:40:00")
        full = msgs(("k", "2026-10-20T15:41:00", "sms"), ("e", "2026-10-21T22:30:00", "email"),
                    ("m", "2026-10-22T13:00:00", "dial"))
        self.assertEqual(cboxes(c, full)["show_sop"]["a"], S.YES)
        b = cboxes(c, full[:2])["show_sop"]
        self.assertEqual(b["a"], S.NO)
        self.assertIn("morning confirm: no", b["why"])
        self.assertEqual(cboxes(c, full[1:])["show_sop"]["a"], S.NO)       # no booking confirmation

    def test_showed(self):
        past = call("2026-10-22T18:00:00", "2026-10-20T15:40:00", "showed")
        self.assertEqual(cboxes(past, [])["showed"]["a"], S.YES)
        self.assertEqual(cboxes(dict(past, status="noshow"), [])["showed"]["a"], S.NO)
        c = dict(past, status="confirmed")
        after, before = T("2026-10-22T18:40:00"), T("2026-10-21T12:00:00")
        self.assertEqual(cboxes(c, [], stage="No Show", stage_at=after)["showed"]["a"], S.NO)
        b = cboxes(c, [], stage="Follow Up", stage_at=after)["showed"]
        self.assertEqual(b["a"], S.YES)
        self.assertIn("deal moved to Follow Up on Thu Oct 22, 2:40pm, after the call", b["why"])
        self.assertEqual(cboxes(c, [], stage="Follow Up", latest=False, stage_at=after)["showed"]["a"], S.UNKNOWN)
        # a stage set before the call, or with no change time, says nothing about the call
        self.assertEqual(cboxes(c, [], stage="Follow Up", stage_at=before)["showed"]["a"], S.UNKNOWN)
        self.assertEqual(cboxes(c, [], stage="No Show")["showed"]["a"], S.UNKNOWN)
        self.assertEqual(cboxes(c, [], notes=[{"when": "2026-10-22T19:00:00Z", "text": "No-show, texted"}])
                         ["showed"]["a"], S.NO)
        self.assertEqual(cboxes(c, [], notes=[{"when": "2026-10-22T19:00:00Z", "text": "OUTCOME: talked"}])
                         ["showed"]["a"], S.YES)
        # an OUTCOME note from the triage call an hour before is not the meeting's outcome
        self.assertEqual(cboxes(c, [], notes=[{"when": "2026-10-22T17:00:00Z", "text": "OUTCOME: will join"}])
                         ["showed"]["a"], S.UNKNOWN)
        self.assertEqual(cboxes(c, [], fields={"showed": "Yes"})["showed"]["a"], S.YES)
        self.assertEqual(cboxes(c, [])["showed"]["a"], S.UNKNOWN)
        ahead = call("2026-11-20T18:00:00", "2026-11-10T15:40:00")
        b = cboxes(ahead, [], now=T("2026-11-12T12:00:00"))["showed"]
        self.assertEqual((b["a"], b["pending"]), (S.NOT_DUE, True))


class QualifiedTest(unittest.TestCase):
    def test_rules(self):
        s = prof.load_settings()
        self.assertEqual(S.qualified({"fields": {}}, "Follow Up", s)[0], True)
        self.assertEqual(S.qualified({"fields": {}}, "Unqualified", s), (False, "deal stage Unqualified"))
        self.assertEqual(S.qualified({"fields": {"outcome_reason": "Wrong Fit"}}, "", s)[0], False)
        self.assertEqual(S.qualified({"fields": {"outcome": ["Disqualified"]}}, "", s)[0], False)
        s["qualified"]["overrides"] = {"41": "no", "12": "yes"}
        self.assertEqual(S.qualified({"fields": {"reply_code": 41.0}}, "", s)[0], False)
        self.assertEqual(S.qualified({"fields": {"reply_code": "12", "outcome_reason": "Wrong Fit"}}, "", s)[0], True)


class MergeCallsTest(unittest.TestCase):
    def ev(self, eid, cal, start, booked, status="confirmed", kind="discovery", cid="c1"):
        return {"id": eid, "cal": cal, "contactId": cid, "start": start, "booked_at": booked, "status": status,
                "deleted": False, "title_kind": kind}

    def test_rules(self):
        s_calls = prof.load_settings()["calls"]
        evs = [self.ev("a", "discovery", "2026-10-22T18:00:00Z", "2026-10-20T15:40:00Z"),
               self.ev("a_copy", "lead_suite", "2026-10-22T18:20:00Z", "2026-10-20T15:41:00Z"),     # Google copy
               self.ev("b", "lead_suite", "2026-10-25T18:00:00Z", "2026-10-21T15:00:00Z", kind="other"),
               self.ev("c", "discovery", "2026-10-26T18:00:00Z", "2026-10-21T15:00:00Z", kind="client"),
               self.ev("d1", "discovery", "2026-10-27T18:00:00Z", "2026-10-21T16:00:00Z", status="cancelled"),
               self.ev("d2", "discovery", "2026-10-28T18:00:00Z", "2026-10-21T16:20:00Z"),
               self.ev("x", "discovery", "2026-10-29T18:00:00Z", "2026-10-21T16:20:00Z", cid="someone_else"),
               self.ev("y1", "discovery", "2026-10-30T18:00:00Z", "2026-10-21T16:00:00Z", status="cancelled", cid="c2")]
        got = {e["id"]: e["_state"] for e in S.merge_calls(evs, {"c1": 1, "c2": 1}, s_calls)}
        self.assertEqual(got, {"a": "booked", "d1": "moved", "d2": "booked", "y1": "cancelled"})

    def test_lead_suite_copy_alone_counts(self):
        s_calls = prof.load_settings()["calls"]
        evs = [self.ev("z", "lead_suite", "2026-10-22T18:00:00Z", "2026-10-20T15:41:00Z")]
        self.assertEqual([e["id"] for e in S.merge_calls(evs, {"c1": 1}, s_calls)], ["z"])


class ZoneTest(unittest.TestCase):
    def test_zone_of(self):
        for txt, want in (("America/Chicago", "central"), ("US/Pacific", "pacific"), ("America/Phoenix", "arizona"),
                          ("Pacific/Honolulu", "hawaii"), ("America/Denver", "mountain"), ("EST", "eastern"),
                          ("", "eastern"), ("Central", "central"), ("America/Indiana/Indianapolis", "eastern")):
            self.assertEqual(S.zone_of(txt), want, txt)

    def test_local_round_trip_across_dst(self):
        # the night clocks fall back, before and after every zone's switch (1am to 2am local happens twice, so an
        # instant inside that repeated hour cannot round-trip and is skipped)
        for iso in ("2026-11-01T04:30:00", "2026-11-01T11:30:00", "2026-03-08T06:30:00", "2026-07-01T12:00:00"):
            u = T(iso)
            for z in ("eastern", "central", "pacific", "arizona"):
                self.assertEqual(S.to_utc(S.local(u, z), z), u, (iso, z))
        self.assertEqual(S.local(T("2026-11-01T13:00:00"), "eastern").hour, 8)     # EST after the switch
        self.assertEqual(S.local(T("2026-10-31T13:00:00"), "eastern").hour, 9)     # EDT before it
        self.assertEqual(S.local(T("2026-07-01T19:00:00"), "arizona").hour, 12)    # no daylight time
        # each zone switches at 2am on its own clock: Central falls back at 07:00 UTC, an hour after Eastern
        self.assertEqual(S.local(T("2026-11-01T06:30:00"), "central").hour, 1)     # 1:30am CDT
        self.assertEqual(S.local(T("2026-11-01T07:30:00"), "central").hour, 1)     # 1:30am CST
        self.assertEqual(S.to_utc(dt.datetime(2026, 11, 1, 0, 0), "central"), T("2026-11-01T05:00:00"))
        self.assertEqual(S.local(T("2026-03-08T08:30:00"), "central").hour, 3)     # 3:30am CDT, just after the jump
        self.assertEqual(S.local(T("2026-03-08T09:30:00"), "pacific").hour, 1)     # still 1:30am PST
        for iso in ("2026-11-01T05:30:00", "2026-11-01T06:30:00", "2026-11-01T07:30:00", "2026-11-01T09:30:00"):
            for z in ("eastern", "central", "mountain", "pacific"):
                self.assertEqual(S.offset_hours(z, T(iso)) - S.ZONES[z][0] in (0, 1), True)


if __name__ == "__main__":
    unittest.main()
