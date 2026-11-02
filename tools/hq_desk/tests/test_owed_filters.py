"""Owed-field lines that are not real promises from Joey stay off the desk (live run, 11/2)."""
import unittest

from tools.hq_desk import score as S


class OwedFilters(unittest.TestCase):
    def test_planner_saying_nothing_is_owed(self):
        self.assertTrue(S.is_empty("nothing open (Joey re-gave the price on the 10/30 call)"))
        self.assertTrue(S.is_empty("None owed"))

    def test_split_fragments(self):
        self.assertTrue(S.is_empty("since"))
        self.assertTrue(S.is_empty(" and; "))

    def test_lead_owes_it(self):
        self.assertTrue(S.is_empty("she will check our reviews/website (10/6)"))
        self.assertTrue(S.is_empty("They will send the license number"))

    def test_real_promises_stay(self):
        self.assertFalse(S.is_empty("Joey owes his price to teach her to run ads"))
        self.assertFalse(S.is_empty("Baltimore City answer"))
        self.assertFalse(S.is_empty("one-page plan for the partners"))

    def test_owed_field_parsing_drops_noise(self):
        items = S.parse_owed_field("2026-10-30: nothing open; since\n2026-10-20: send the plan PDF", S.et.now_utc())
        self.assertEqual([i["text"] for i in items], ["send the plan PDF"])


if __name__ == "__main__":
    unittest.main()
