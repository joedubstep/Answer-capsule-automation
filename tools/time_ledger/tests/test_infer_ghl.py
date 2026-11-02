import datetime as dt
import json
import os
import unittest

from tools.time_ledger import ghl_calls as G
from tools.time_ledger import infer as I
from tools.time_ledger import minutes as M
from tools.time_ledger import parse as P
from tools.time_ledger.tests.base import FIX, by, page_fetch_json

DAY = dt.date(2026, 11, 1)


class FakeGHL(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("GHL_FAKE_DIR")
        os.environ["GHL_FAKE_DIR"] = os.path.join(FIX, "ghl")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GHL_FAKE_DIR", None)
        else:
            os.environ["GHL_FAKE_DIR"] = self._old


class GhlCallsTests(FakeGHL):
    def test_pull_keeps_calls_only_and_no_personal_data(self):
        data = G.pull(DAY)
        self.assertNotIn("unavailable", data)
        self.assertEqual(len(data["calls"]), 5)                       # the text message is dropped
        self.assertEqual(data["calls"][0]["clock"], "7:30 am")
        raw = json.dumps(data)
        for bad in ("+1555", "cSample", "Sample text", "Pat"):
            self.assertNotIn(bad, raw)
        s = G.summary(data, 16 * 60 + 37, 19 * 60)
        self.assertEqual((s["dials"], s["answered"], s["talk_min"]), (3, 1, 2.7))

    def test_no_access(self):
        os.environ["GHL_FAKE_DIR"] = os.path.join(FIX, "nothing_here")
        data = G.pull(DAY)
        self.assertIn("unavailable", data)
        self.assertEqual(data["calls"], [])

    def test_day_window_is_4am_to_4am_eastern(self):
        s, e = G.day_window(DAY)
        self.assertEqual(s.isoformat(), "2026-11-01T09:00:00+00:00")     # EST after the Nov 1 change
        self.assertEqual(e.isoformat(), "2026-11-02T09:00:00+00:00")


class InferTests(FakeGHL):
    def setUp(self):
        super().setUp()
        self.rows = M.estimate(P.parse_page(page_fetch_json())["rows"])
        self.blanks = [r for r in self.rows if r["type"] == "blank"]

    def test_windows(self):
        w = {(x["date"], x["start"]): x["end"] for x in I.blank_windows(self.blanks)}
        self.assertEqual(w[("2026-11-01", 16 * 60 + 37)], 19 * 60)
        self.assertEqual(w[("2026-11-01", 19 * 60)], 19 * 60 + 15)

    def test_calendar_meeting_and_gmail(self):
        ev = {"events": [
            {"summary": "Weekly sample call", "status": "confirmed",
             "start": {"dateTime": "2026-11-01T18:30:00-05:00"}, "end": {"dateTime": "2026-11-01T19:00:00-05:00"},
             "attendees": [{"email": "owner@example.com", "self": True, "responseStatus": "accepted"},
                           {"email": "pat@example.com", "responseStatus": "accepted"}]},
            {"summary": "Focus block", "status": "confirmed", "recurringEventId": "r1",
             "start": {"dateTime": "2026-11-01T17:00:00-05:00"}, "end": {"dateTime": "2026-11-01T18:00:00-05:00"}},
            {"summary": "Cancelled call", "status": "cancelled",
             "start": {"dateTime": "2026-11-01T17:00:00-05:00"}, "end": {"dateTime": "2026-11-01T17:30:00-05:00"}},
            {"summary": "All day", "start": {"date": "2026-11-01"}, "end": {"date": "2026-11-02"}}]}
        gm = [{"source": "gmail", "start": "2026-11-01T17:10:00-05:00", "title": "Sample follow up"},
              {"source": "gmail", "start": "2026-11-01T09:10:00-05:00", "title": "Outside the window"}]
        out = I.infer(self.blanks, [ev, gm])
        b = by(out, log_date="2026-11-01", block_label="4:37 pm")
        texts = [r["action_text"] for r in b]
        self.assertEqual(texts, ["Meeting: Weekly sample call (inferred)",
                                 "Sent 1 email, e.g. \"Sample follow up\" (inferred)"])
        self.assertEqual(b[0]["minutes"], 30)
        self.assertTrue(all(r["source"] == "inferred" and r["minutes_est"] for r in b))
        self.assertTrue(all(r["confidence"] <= 0.6 for r in b))
        self.assertEqual(len({r["key"] for r in out}), len(out))
        self.assertFalse([r for r in out if "Focus block" in r["action_text"] or "Cancelled" in r["action_text"]])

    def test_ghl_calls_become_a_sales_row(self):
        g = {"2026-11-01": G.pull(DAY)}
        out = I.infer(self.blanks, [], g)
        b = by(out, log_date="2026-11-01", block_label="4:37 pm")
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["role"], "Sales")
        self.assertEqual(b[0]["kind"], "Outreach")
        self.assertIn("Made 3 calls in GoHighLevel, 1 answered", b[0]["action_text"])

    def test_keys_are_stable_per_block(self):
        ev = [{"source": "calendar", "start": "2026-11-01T18:30:00-05:00", "end": "2026-11-01T19:00:00-05:00",
               "title": "One title", "attendees": 1}]
        ev2 = [dict(ev[0], title="Another title")]
        a = I.infer(self.blanks, ev)
        b = I.infer(self.blanks, ev2)
        self.assertEqual([r["key"] for r in a], [r["key"] for r in b])
        blank = by(self.blanks, log_date="2026-11-01", block_label="4:37 pm")[0]
        self.assertIn(a[0]["key"], I.block_keys(blank))

    def test_email_header_dates(self):
        gm = [{"source": "gmail", "start": "Sun, 1 Nov 2026 17:10:00 -0500", "title": "Header date"}]
        out = I.infer(self.blanks, gm)
        self.assertEqual([r["action_text"] for r in out], ["Sent 1 email, e.g. \"Header date\" (inferred)"])

    def test_nothing_found(self):
        self.assertEqual(I.infer(self.blanks, []), [])

    def test_plan(self):
        plan = I.evidence_plan(I.blank_windows(self.blanks))
        d = [p for p in plan if p["date"] == "2026-11-01"][0]
        self.assertEqual(d["calendar"]["startTime"], "2026-11-01T16:37:00")
        self.assertEqual(d["gmail_query"], "in:sent -to:me after:2026/11/01 before:2026/11/02")
        plan = I.evidence_plan(I.blank_windows(self.blanks), ["primary", "sample@group.calendar.google.com"])
        self.assertEqual(plan[0]["calendar"]["calendarIds"], ["primary", "sample@group.calendar.google.com"])

    def test_gmail_time_from_message_id(self):
        sent = dt.datetime(2026, 11, 1, 22, 10, tzinfo=dt.timezone.utc)          # 5:10 pm ET
        mid = "%x" % ((int(sent.timestamp() * 1000) << 20) | 0x5f2)
        self.assertEqual(I.gmail_id_time(mid), sent)
        self.assertIsNone(I.gmail_id_time("not-hex"))
        self.assertIsNone(I.gmail_id_time("12"))
        out = I.infer(self.blanks, [{"source": "gmail", "id": mid, "title": "Id only"}])
        self.assertEqual([r["action_text"] for r in out], ["Sent 1 email, e.g. \"Id only\" (inferred)"])
        self.assertEqual(out[0]["block_label"], "4:37 pm")
        reply = I.infer(self.blanks, [{"source": "gmail", "id": mid, "title": "Accepted: Sample call @ Weekly"}])
        self.assertEqual(reply, [])


if __name__ == "__main__":
    unittest.main()
