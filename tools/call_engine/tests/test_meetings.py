import datetime as dt
import json
import os
import unittest

from tools.call_engine import meetings as mt

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def listing():
    with open(os.path.join(FIX, "meetings_list.txt"), encoding="utf-8") as f:
        return mt.parse_list(f.read())


class ParseTests(unittest.TestCase):
    def test_text_list(self):
        ms = listing()
        self.assertEqual(len(ms), 9)
        robin = next(m for m in ms if m["recording_id"] == "900000005")
        self.assertEqual(robin["title"], "Discovery Call | Joey x Robin Sample")    # a "|" inside the title
        self.assertEqual(robin["call_id"], "111111105")
        self.assertEqual(robin["invitees"], ["robin@example.com"])
        self.assertEqual(robin["recorded_by"], "Joey Host")
        group = next(m for m in ms if m["recording_id"] == "900000006")
        self.assertEqual(len(group["invitees"]), 5)

    def test_json_list(self):
        data = json.dumps({"meetings": [{"title": "Pat discovery", "created_at": "2026-10-29T15:00:00Z",
                                         "recording_id": 5, "url": "https://fathom.video/calls/77",
                                         "calendar_invitees": [{"email": "pat@example.com"}]}]})
        ms = mt.parse_list(data)
        self.assertEqual(ms[0]["date"], "2026-10-29")
        self.assertEqual(ms[0]["call_id"], "77")
        self.assertEqual(ms[0]["invitees"], ["pat@example.com"])


class ClassifyTests(unittest.TestCase):
    def kind(self, title, inv=None):
        return mt.classify({"title": title, "invitees": inv or [], "recording_id": "1"})[0]

    def test_titles(self):
        self.assertEqual(self.kind("joey x Pat Example"), "discovery")
        self.assertEqual(self.kind("Morgan Sample discovery"), "discovery")
        self.assertEqual(self.kind("Discovery Call | Joey x Robin"), "discovery")
        self.assertEqual(self.kind("Drew Sample onboarding"), "onboarding")
        self.assertEqual(self.kind("Pat Sample pt2"), "close")
        self.assertEqual(self.kind("Pat follow up call"), "follow-up")
        self.assertEqual(self.kind("Weekly Mastermind"), "coaching")
        self.assertEqual(self.kind("Vendor proposal call"), "other")
        self.assertEqual(self.kind("Pat discovery (Lead Suite ad)"), "discovery")   # sales words beat weak coach words
        self.assertEqual(self.kind("Lead Suite weekly"), "coaching")

    def test_vague_titles_need_the_model(self):
        self.assertIsNone(self.kind("Impromptu Google Meet Meeting"))
        self.assertIsNone(self.kind("Joey g and Someone Else"))
        self.assertIsNone(self.kind("Gilda"))

    def test_invitees(self):
        self.assertEqual(self.kind("Weekly call", ["coach@leadsuite.agency"]), "coaching")
        self.assertEqual(self.kind("Weekly call", ["a", "b", "c", "d", "e"]), "coaching")

    def test_model_kinds_win(self):
        k, why = mt.classify({"title": "Impromptu Google Meet Meeting", "recording_id": "7"}, {"7": "Discovery"})
        self.assertEqual(k, "discovery")
        self.assertEqual(mt.classify({"title": "x", "recording_id": "7"}, {"7": "weird"})[0], "other")


class SelectTests(unittest.TestCase):
    LIB = {"sales": [{"Link": "https://fathom.video/calls/111111105"}], "ls": []}

    def test_scheduled_window_after_cursor(self):
        r = mt.select_new(listing(), self.LIB, window_days=3, max_n=3, today=dt.date(2026, 10, 30))
        self.assertEqual(r["cursor"], "2026-10-27")
        self.assertEqual([m["recording_id"] for m in r["todo"]], ["900000006", "900000008", "900000009"])
        self.assertEqual([m["recording_id"] for m in r["need_kind"]], ["900000007"])
        self.assertEqual(r["todo"][2]["library"], "sales")
        self.assertEqual(r["todo"][2]["type"], "Discovery")
        self.assertEqual(r["todo"][0]["library"], "ls")

    def test_window_blocks_old_backlog(self):
        r = mt.select_new(listing(), {"sales": [], "ls": []}, window_days=3, max_n=3, today=dt.date(2026, 11, 5))
        self.assertEqual(r["todo"], [])
        self.assertEqual(r["need_kind"], [])

    def test_max_and_waiting(self):
        kinds = {"900000007": "discovery"}
        r = mt.select_new(listing(), self.LIB, window_days=3, max_n=2, kinds=kinds, today=dt.date(2026, 10, 30))
        self.assertEqual(len(r["todo"]), 2)
        self.assertEqual(r["waiting"], 2)

    def test_backfill_since(self):
        lib = {"sales": {"results": [{"Link": "https://fathom.video/calls/111111105"}]},
               "ls": [{"Link": "https://fathom.video/calls/111111106?tab=summary"}]}
        r = mt.select_new(listing(), lib, since="2026-10-01", max_n=10, today=dt.date(2026, 11, 2))
        ids = [m["recording_id"] for m in r["todo"]]
        self.assertEqual(ids, ["900000002", "900000003", "900000008", "900000009"])
        self.assertEqual({s["kind"] for s in r["skipped"]}, {"other", "onboarding"})
        self.assertNotIn("900000006", ids)                              # already in the LS library
        self.assertNotIn("900000005", ids)                              # already in the Sales library

    def test_held_call_is_retried_next_night(self):
        # 10/28 coaching call was held (not written); 10/29 got a row. The next night the 10/28 call is still due.
        lib = {"sales": [{"Link": "https://fathom.video/calls/111111111"}], "ls": []}
        r = mt.select_new(listing(), lib, window_days=4, max_n=3, today=dt.date(2026, 10, 31))
        self.assertEqual(r["cursor"], "2026-10-29")
        self.assertIn("900000008", [m["recording_id"] for m in r["todo"]])

    def test_share_link_rows_are_not_redone(self):
        lib = {"sales": [{"Call": "Pat Example discovery, 2026-10-29", "Link": "https://fathom.video/share/AbC"}],
               "ls": [{"Call": "Mastermind 10/27 \u00b7 offer operators", "Link": "https://fathom.video/share/XyZ"},
                      {"Call": None, "Link": None}]}
        r = mt.select_new(listing(), lib, since="2026-10-20", max_n=10, today=dt.date(2026, 11, 2))
        ids = [m["recording_id"] for m in r["todo"]]
        self.assertNotIn("900000009", ids)                       # same date and name as a share-link sales row
        self.assertNotIn("900000006", ids)                       # coaching call on the date of a share-link LS row
        self.assertIn("900000005", ids)                          # 10/27 sales call: different person, still due
        why = {s["recording_id"]: s["why"] for s in r["skipped"]}
        self.assertIn("probably already in the library", why["900000009"])

    def soft(self, title, date, rows, kind="coaching"):
        return mt.soft_match({"title": title, "date": date}, kind, mt.soft_rows(rows))

    def test_same_date_different_call_type_is_not_a_match(self):
        # a one-on-one with the Lead Suite account manager on the day of a mastermind already in the LS library
        lib = {"sales": [], "ls": [{"Call": "Mastermind 10/1", "Link": "https://fathom.video/share/AbC"}]}
        self.assertIsNone(self.soft("Joey g and Dana Example", "2026-10-01", lib))
        self.assertIsNone(self.soft("Account manager 1:1 coaching", "2026-10-01", lib))
        self.assertIsNone(self.soft("Dana Example coaching call", "2026-10-01", lib))
        self.assertIsNone(self.soft("One on one with Dana", "2026-10-01", lib))
        # two discovery calls the same day with different people are two calls
        sales = {"sales": [{"Call": "Pat Example discovery, 2026-10-27", "Link": "https://fathom.video/share/XyZ"}]}
        self.assertIsNone(self.soft("Robin Sample discovery", "2026-10-27", sales, kind="discovery"))
        # a shared name does not join a one-on-one to a group call
        ls = {"ls": [{"Call": "Mastermind 10/1 with Dana", "Link": ""}]}
        self.assertIsNone(self.soft("Dana 1:1", "2026-10-01", ls))

    def test_same_date_shared_name_or_coaching_keyword_is_a_match(self):
        lib = {"sales": [{"Call": "Pat Example discovery, 2026-10-29", "Link": "https://fathom.video/share/AbC"}],
               "ls": [{"Call": "Dana Example 1:1, 10/1", "Link": ""},
                      {"Call": "Mastermind 10/2", "Link": "https://fathom.video/share/Grp"}]}
        self.assertEqual(self.soft("joey x Pat Example", "2026-10-29", lib, kind="discovery"),
                         "Pat Example discovery, 2026-10-29")
        self.assertEqual(self.soft("Dana Example coaching", "2026-10-01", lib), "Dana Example 1:1, 10/1")
        self.assertEqual(self.soft("Account manager one-on-one", "2026-10-01", lib), "Dana Example 1:1, 10/1")
        self.assertEqual(self.soft("Weekly Mastermind", "2026-10-02", lib), "Mastermind 10/2")
        self.assertIsNone(self.soft("Weekly Mastermind", "2026-10-03", lib))          # the date still has to match

    def test_one_on_one_coaching_call_is_reviewed_not_skipped(self):
        listed = mt.parse_list("- Joey g and Dana Example | 2026-10-01 | id: 900000020 | url: "
                               "https://fathom.video/calls/111111120 | recorded by Joey Host | dana@coach.example.com")
        lib = {"sales": [], "ls": [{"Call": "Mastermind 10/1", "Link": "https://fathom.video/share/AbC"}]}
        kinds = {"900000020": "coaching"}                # the vague title was read from the summary: coaching
        r = mt.select_new(listed, lib, since="2026-10-01", max_n=10, kinds=kinds, today=dt.date(2026, 10, 2))
        self.assertEqual([m["recording_id"] for m in r["todo"]], ["900000020"])
        self.assertEqual(r["todo"][0]["library"], "ls")
        self.assertEqual(r["skipped"], [])

    def test_call_types(self):
        self.assertEqual(mt.call_types("Mastermind 10/1"), ({"mastermind"}, {"group"}))
        self.assertEqual(mt.call_types("Dana 1 on 1")[1], {"one-on-one"})
        self.assertEqual(mt.call_types("Pat 11:15 call 10/11"), (set(), set()))      # times and dates are not 1:1
        self.assertNotIn("manager", mt.name_tokens("Account manager call with Dana"))

    def test_link_keys(self):
        self.assertIn("call:42", mt.link_keys("https://fathom.video/calls/42?timestamp=3"))
        self.assertIn("share:AbC_d-1", mt.link_keys("https://fathom.video/share/AbC_d-1"))
        self.assertEqual(mt.link_keys(""), set())


class PriorTests(unittest.TestCase):
    def test_prior_by_name_and_email(self):
        ms = listing()
        p = mt.prior(ms, "Pat Example", before="2026-11-01")
        self.assertEqual([x["recording_id"] for x in p], ["900000009", "900000002"])
        self.assertEqual([x["recording_id"] for x in mt.prior(ms, "Robin Sample")], ["900000005"])
        self.assertEqual([x["recording_id"] for x in mt.prior(ms, None, "pat@example.com")], ["900000002"])
        self.assertEqual(mt.prior(ms, "Nobody Here"), [])
        first_only = [mt._norm({"title": "Casey discovery", "date": "2026-10-05", "recording_id": "1",
                                "url": "https://fathom.video/calls/1", "invitees": []})]
        p = mt.prior(first_only, "Casey Sample")                 # Joey's titles usually hold the first name only
        self.assertEqual([(x["recording_id"], x["match"]) for x in p], [("1", "first name")])
        self.assertEqual(p and mt.prior(ms, "Pat Example")[0]["match"], "full name")


if __name__ == "__main__":
    unittest.main()
