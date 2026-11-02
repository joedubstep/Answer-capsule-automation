import unittest

from tools.time_ledger import minutes as M
from tools.time_ledger import parse as P
from tools.time_ledger.tests.base import by, page_fetch_json


def rows():
    return M.estimate(P.parse_page(page_fetch_json())["rows"])


class NamedMinutesTests(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(M.named_minutes("check email for 5 minutes."), 5)
        self.assertEqual(M.named_minutes("spent about 30 minutes reading the handbook"), 30)
        self.assertEqual(M.named_minutes("got distracted in the app for 17-ish minutes"), 17)
        self.assertEqual(M.named_minutes("scrolled the phone for 30"), 30)
        self.assertEqual(M.named_minutes("spent 15 more minutes on the bonus list"), 15)
        self.assertAlmostEqual(M.named_minutes("check the app for 30 seconds"), 0.5)
        self.assertEqual(M.named_minutes("watched videos until 12:04", block_min=11 * 60 + 35), 29)
        self.assertEqual(M.named_minutes("write N1", block_min=1369, done_min=1411), 42)

    def test_not_durations(self):
        self.assertIsNone(M.named_minutes("write N2, a short story (saves 4 hours a week)"))
        self.assertIsNone(M.named_minutes("check the 15-minute tracker"))
        self.assertIsNone(M.named_minutes("cut wait time from 3 hours down to 9 minutes"))
        self.assertIsNone(M.named_minutes("drop the 10 replies within 48 hours rule"))


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.rows = rows()

    def test_everything_is_an_estimate(self):
        self.assertTrue(all(r["minutes_est"] for r in self.rows))
        self.assertTrue(all(r["minutes"] >= 0 for r in self.rows))

    def test_gap_is_capped_at_30(self):
        b = by(self.rows, log_date="2026-11-01", block_label="4:00 pm")       # next block 4:37 pm
        self.assertAlmostEqual(sum(r["minutes"] for r in b), 30, delta=0.3)
        b = by(self.rows, log_date="2026-10-27", block_label="8:50 pm")       # next block 9:15 pm
        self.assertAlmostEqual(sum(r["minutes"] for r in b), 25, delta=0.3)

    def test_named_durations_kept(self):
        b = by(self.rows, log_date="2026-11-01", block_label="7:30 am")
        self.assertEqual([r["minutes"] for r in b], [5, 15, 5])

    def test_named_total_over_cap_uses_gap(self):
        b = by(self.rows, log_date="2026-10-27", block_label="10:49 pm")       # N1 done 11:31
        self.assertEqual(b[0]["minutes"], 42)

    def test_untimed_block_shares_gap(self):
        d = by(self.rows, log_date="2026-10-31")
        seg = [r for r in d if r["block_label"] in ("10:40 am", "after 10:40 am")]
        self.assertAlmostEqual(sum(r["minutes"] for r in seg), 50, delta=0.5)   # 10:40 to 11:30
        until = by(self.rows, log_date="2026-10-31", block_label="11:30 am")
        self.assertEqual(until[0]["minutes"], 22)

    def test_breaks(self):
        lead = by(self.rows, log_date="2026-10-27", block_label="9:15 pm")
        self.assertEqual(lead[0]["minutes"], 55)                                # 9:15 to back 10:10
        self.assertEqual(lead[1]["minutes"], 1)                                 # 10:10 to 10:11
        nob = by(self.rows, log_date="2026-10-26", block_label="9:18 am")       # no back time: gap 64
        self.assertEqual(nob[0]["minutes"], 34)
        self.assertAlmostEqual(sum(r["minutes"] for r in nob[1:]), 30, delta=0.3)
        end = by(self.rows, log_date="2026-11-01", block_label="8:05 am")       # stopping work, next at 4:00 pm
        self.assertEqual(end[-1]["type"], "break")
        self.assertEqual(end[-1]["minutes"], 475 - 30)

    def test_blank_window(self):
        b = by(self.rows, log_date="2026-11-01", block_label="4:37 pm")[0]
        self.assertEqual(b["minutes"], 30)
        self.assertEqual(b["window_start"], 16 * 60 + 37)
        self.assertEqual(b["next_start"], 19 * 60)
        last = by(self.rows, log_date="2026-11-01", block_label="7:00 pm")[0]
        self.assertEqual(last["minutes"], 15)
        self.assertIsNone(last["next_start"])

    def test_day_totals(self):
        t = M.day_totals(self.rows)["2026-11-01"]
        self.assertGreater(t["work"], 50)
        self.assertGreater(t["breaks"], 400)
        self.assertEqual(t["blank"], 45)


if __name__ == "__main__":
    unittest.main()
