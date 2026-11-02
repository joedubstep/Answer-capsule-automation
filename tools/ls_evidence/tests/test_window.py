"""The 90-day clock, the pause, and the scoreboard math."""
import copy
import datetime as dt
import unittest

from tools.ls_evidence import profile as prof
from tools.ls_evidence import score as S

D = dt.date.fromisoformat


class ClockTest(unittest.TestCase):
    def setUp(self):
        self.s = prof.load_settings()

    def test_pause_does_not_burn_the_clock(self):
        w = S.clock_window(self.s, D("2026-11-02"))
        self.assertEqual((w["live"], w["end"]), ("2026-08-08", "2026-11-16"))
        self.assertEqual(w["paused_days"], 11)                 # Aug 14 to 24, both included
        self.assertEqual((w["used"], w["left"]), (76, 14))    # 6 before the pause + 70 from Aug 25 to Nov 2
        self.assertFalse(w["over"])

    def test_without_the_pause(self):
        s = copy.deepcopy(self.s)
        s["ads"]["pauses"] = []
        w = S.clock_window(s, D("2026-11-02"))
        self.assertEqual(w["end"], "2026-11-05")
        self.assertEqual((w["used"], w["left"]), (87, 3))

    def test_a_pause_that_burns_the_clock_is_ignored(self):
        s = copy.deepcopy(self.s)
        s["ads"]["pauses"][0]["burns_clock"] = True
        self.assertEqual(S.clock_window(s, D("2026-11-02"))["end"], "2026-11-05")

    def test_days_during_the_pause_and_edges(self):
        self.assertEqual(S.clock_window(self.s, D("2026-08-08"))["used"], 1)
        self.assertEqual(S.clock_window(self.s, D("2026-08-13"))["used"], 6)
        self.assertEqual(S.clock_window(self.s, D("2026-08-20"))["used"], 6)    # paused: the clock stands still
        self.assertEqual(S.clock_window(self.s, D("2026-08-25"))["used"], 7)
        w = S.clock_window(self.s, D("2026-11-16"))
        self.assertEqual((w["used"], w["left"], w["over"]), (90, 0, False))
        w = S.clock_window(self.s, D("2026-11-20"))
        self.assertEqual((w["used"], w["left"], w["over"]), (90, 0, True))
        w = S.clock_window(self.s, D("2026-08-01"))
        self.assertEqual((w["used"], w["started"]), (0, False))

    def test_dst_night_is_one_day(self):
        a = S.clock_window(self.s, D("2026-10-31"))["used"]
        b = S.clock_window(self.s, D("2026-11-01"))["used"]
        c = S.clock_window(self.s, D("2026-11-02"))["used"]
        self.assertEqual((b - a, c - b), (1, 1))

    def test_window_end_is_midnight_after_the_last_day(self):
        w = S.clock_window(self.s, D("2026-11-02"))
        self.assertEqual(w["end_utc"], "2026-11-17T05:00:00+00:00")       # Nov 17 0:00 EST
        self.assertEqual(S.live_start_utc(self.s).isoformat(), "2026-08-08T04:00:00+00:00")   # Aug 8 0:00 EDT


def call_row(counts=True, state="booked", in_window=True, qualified=True, showed=S.YES, upcoming=False, h="x"):
    return {"counts": counts, "state": state, "in_window": in_window, "qualified": qualified, "upcoming": upcoming,
            "lead_hash": h, "boxes": {"showed": {"a": showed}}}


class ScoreboardTest(unittest.TestCase):
    def setUp(self):
        self.s = prof.load_settings()
        self.sop = {"leads": {"yes": 8, "no": 2, "pct": 80}, "calls": {"yes": 0, "no": 0, "pct": None}}

    def board(self, calls, today):
        w = S.clock_window(self.s, D(today))
        return S.scoreboard(self.s, w, calls, [], self.sop, D(today))

    def test_counts_and_pace(self):
        calls = [call_row(h=str(i)) for i in range(12)] + [
            call_row(counts=False, qualified=False), call_row(counts=False, state="cancelled"),
            call_row(counts=False, state="moved"), call_row(showed=S.NO, h="12"), call_row(upcoming=True, h="13")]
        b = self.board(calls, "2026-11-02")
        self.assertEqual(b["qualified_booked"], 14)
        self.assertEqual(b["booked_in_window"], 15)     # cancelled and moved rows are not bookings
        self.assertEqual(b["unqualified"], 1)
        self.assertEqual(b["cancelled"], 1)
        self.assertEqual(b["held"], 13)
        self.assertEqual(b["upcoming"], 1)
        self.assertEqual(b["need"], 16)
        self.assertEqual(b["pace"], round(14 * 90 / 76))
        self.assertIn("14 of 30 qualified calls with 14 days left", b["line"])
        self.assertIn("At this pace the window ends with about 17 calls.", b["line"])
        self.assertIn("80% of due boxes done", b["line"])
        self.assertIn("Meta and Mercury", b["line"])

    def test_target_reached(self):
        b = self.board([call_row(h=str(i)) for i in range(30)], "2026-11-02")
        self.assertIn("hit the 30-call number", b["line"])
        self.assertEqual(b["need"], 0)

    def test_window_closed_under_target(self):
        b = self.board([call_row()], "2026-11-20")
        self.assertIn("The window closed Mon Nov 16 with 1 of 30", b["line"])
        self.assertIn("refund applies if the proof holds", b["line"])

    def test_not_started(self):
        self.assertIn("Ads are not live yet", self.board([], "2026-08-01")["line"])

    def test_no_forbidden_words(self):
        for today, calls in (("2026-11-02", []), ("2026-11-20", []), ("2026-11-02", [call_row(h=str(i)) for i in range(30)])):
            line = self.board(calls, today)["line"].lower()
            self.assertNotIn("chargeback", line)
            self.assertNotIn("recording", line)


if __name__ == "__main__":
    unittest.main()
