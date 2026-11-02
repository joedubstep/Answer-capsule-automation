import datetime as dt
import unittest

from tools.time_ledger import common as C
from tools.time_ledger import parse as P
from tools.time_ledger.tests.base import EDITED, by, page_fetch_json, page_md


class LoadTests(unittest.TestCase):
    def test_fetch_json_gives_text_and_edit_time(self):
        text, edited = P.load_page(page_fetch_json())
        self.assertIn("## 15 min log 11/1", text)
        self.assertEqual(edited, EDITED)
        self.assertNotIn("<content>", text)

    def test_tool_result_list_wrapper(self):
        import json
        wrapped = json.dumps([{"type": "text", "text": page_fetch_json()}])
        text, edited = P.load_page(wrapped)
        self.assertEqual(edited, EDITED)
        self.assertIn("15 min log 10/24", text)

    def test_markdown_only(self):
        text, edited = P.load_page(page_md())
        self.assertIsNone(edited)
        self.assertIn("15 min log 10/25", text)


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.res = P.parse_page(page_fetch_json())
        self.rows = self.res["rows"]
        self.secs = self.res["sections"]

    def test_all_heading_forms_found(self):
        heads = [s["heading_date"] for s in self.secs]
        self.assertEqual(heads, ["2026-11-01", "2026-11-01", "2026-10-31", "2026-10-27", "2026-10-26",
                                 "2026-10-26", "2026-10-25", "2026-10-24"])

    def test_top_duplicate_moves_to_edit_day(self):
        top = self.secs[0]
        self.assertEqual(top["resolved"], "2026-11-02")
        self.assertTrue(top["suspect"])
        self.assertEqual(self.secs[1]["resolved"], "2026-11-01")
        self.assertTrue(by(self.rows, log_date="2026-11-02", block_label="7:50 am"))
        self.assertTrue(all(r["flags"]["date_suspect"] for r in by(self.rows, log_date="2026-11-02")))
        self.assertEqual({r["heading_date"] for r in by(self.rows, log_date="2026-11-02")}, {"2026-11-01"})

    def test_lower_duplicate_is_evening_of_day_before(self):
        self.assertEqual(self.secs[4]["resolved"], "2026-10-26")
        self.assertEqual(self.secs[5]["resolved"], "2026-10-25")
        eve = by(self.rows, log_date="2026-10-25", block_label="7:48 pm")
        self.assertTrue(eve)
        # merged with the real 10/25 morning in time order
        labels = []
        for r in by(self.rows, log_date="2026-10-25"):
            if r["block_label"] not in labels:
                labels.append(r["block_label"])
        self.assertEqual(labels, ["6:48 am", "7:15 am", "7:48 pm", "8:13 pm", "9:15 pm"])

    def test_no_resolution_without_edit_time(self):
        res = P.parse_page(page_md(), today=dt.date(2026, 11, 2))
        self.assertEqual(res["sections"][0]["resolved"], "2026-11-01")
        self.assertTrue(res["sections"][0]["suspect"])

    def test_edit_time_before_content_blocks_the_move(self):
        res = P.parse_page(page_md(), edited="2026-11-02T13:00:00Z")      # 8:00 am ET, before the 9:05 block
        self.assertEqual(res["sections"][0]["resolved"], "2026-11-01")

    def test_only_free_day_between_headings(self):
        text = page_md().replace("## 15 min log 11/1\n\n<ul>\n<li>\n7:50 am",
                                 "## 15 min log 11/3\n\n<ul>\n<li>\n7:10 am/ check email /\n</li>\n</ul>\n\n"
                                 "## 15 min log 11/1\n\n<ul>\n<li>\n7:50 am", 1)
        res = P.parse_page(text, edited="2026-11-03T15:00:00Z")
        self.assertEqual([s["resolved"] for s in res["sections"][:3]], ["2026-11-03", "2026-11-02", "2026-11-01"])

    def test_loose_paragraph_is_a_note_not_a_block(self):
        self.assertGreaterEqual(self.res["notes_skipped"], 1)
        self.assertFalse([r for r in self.rows if "Reminder" in r["action_text"]])

    def test_non_log_content_ignored(self):
        self.assertFalse([r for r in self.rows if "Example task" in r["action_text"]])


class MultiDayTests(unittest.TestCase):
    """Joey keeps writing the next morning under the same (already wrong) top heading."""

    def page(self):
        return page_md().replace("<li>\n9:05 am/\n</li>",
                                 "<li>\n9:05 am/ call the sample vendor\n</li>\n<li>\n7:40 am/ sort the inbox / "
                                 "plan the day\n</li>\n<li>\n8:10 am/ write the sample report\n</li>", 1)

    def test_section_holding_two_days_is_split(self):
        res = P.parse_page(self.page(), edited="2026-11-03T14:00:00Z")      # 9:00 am ET on Nov 3
        top = res["sections"][0]
        self.assertEqual((top["resolved"], top["last_day"]), ("2026-11-02", "2026-11-03"))
        self.assertTrue(top["suspect"])
        rows = res["rows"]
        self.assertEqual([r["block_label"] for r in by(rows, log_date="2026-11-03")],
                         ["7:40 am", "7:40 am", "8:10 am"])
        self.assertEqual(by(rows, log_date="2026-11-03")[0]["block_min"], 7 * 60 + 40)
        self.assertTrue(by(rows, log_date="2026-11-02", block_label="9:05 am"))
        self.assertEqual(res["sections"][1]["resolved"], "2026-11-01")

    def test_keys_of_the_first_day_do_not_change(self):
        before = {r["key"] for r in P.parse_page(page_md(), edited=EDITED)["rows"]
                  if r["log_date"] == "2026-11-02" and r["type"] == "action"}
        after = {r["key"] for r in P.parse_page(self.page(), edited="2026-11-03T14:00:00Z")["rows"]
                 if r["log_date"] == "2026-11-02"}
        self.assertTrue(before <= after)

    def test_edit_after_midnight_counts_as_the_work_day(self):
        text = page_md().replace("<li>\n9:05 am/\n</li>", "<li>\n9:05 am/ x\n</li>\n<li>\n11:50 pm/ late task\n"
                                 "</li>\n<li>\n12:20 am/ later task\n</li>", 1)
        res = P.parse_page(text, edited="2026-11-03T05:30:00Z")             # 12:30 am ET on Nov 3
        self.assertEqual(res["sections"][0]["resolved"], "2026-11-02")
        late = by(res["rows"], log_date="2026-11-02", block_label="12:20 am")
        self.assertEqual(late[0]["block_min"], 1440 + 20)

    def test_section_opening_after_midnight_is_one_day(self):
        text = page_md().replace("<li>\n1033/ move notes", "<li>\n12:30 am/ wrap up\n</li>\n<li>\n9:00 am/ next\n"
                                 "</li>\n<li>\n1033/ move notes", 1)
        res = P.parse_page(text, edited=EDITED)
        sec = [s for s in res["sections"] if s["heading_date"] == "2026-10-24"][0]
        self.assertEqual(sec["last_day"], "2026-10-24")


class BlockTests(unittest.TestCase):
    def setUp(self):
        self.rows = P.parse_page(page_fetch_json())["rows"]

    def test_clock_forms(self):
        d24 = by(self.rows, log_date="2026-10-24")
        self.assertEqual(d24[0]["block_label"], "10:33 pm")          # "1033" read from the next block's pm
        self.assertEqual(d24[0]["block_min"], 22 * 60 + 33)
        mid = by(self.rows, log_date="2026-10-24", block_label="12:00 am")
        self.assertEqual(mid[0]["block_min"], 1440)                  # "12 am" after 11:04 pm is past midnight
        b437 = by(self.rows, log_date="2026-11-01", block_label="4:37 pm")
        self.assertEqual(len(b437), 1)
        self.assertTrue(b437[0]["flags"]["blank"])
        late = by(self.rows, log_date="2026-10-27", block_label="12:07 am")
        self.assertEqual(late[0]["block_min"], 1447)
        bare = by(self.rows, log_date="2026-10-25", block_label="9:15 pm")
        self.assertTrue(bare)

    def test_actions_split_on_slash_and_and_then(self):
        b = by(self.rows, log_date="2026-10-31", block_label="10:40 am")
        self.assertEqual([r["action_text"] for r in b],
                         ["listed new bonus ideas for like 10 minutes", "scrolled the phone for 20"])
        self.assertEqual([r["position"] for r in b], [0, 1])

    def test_dates_inside_text_not_split(self):
        b = by(self.rows, log_date="2026-10-25", block_label="6:48 am")
        texts = [r["action_text"] for r in b]
        self.assertIn("fix the notes file from 1/10 to 1/20", texts)
        self.assertIn("look at example.com pages", texts)
        self.assertIn("read the $100 budget notes", texts)

    def test_blank_blocks(self):
        blanks = [r for r in self.rows if r["type"] == "blank"]
        self.assertEqual(sorted((r["log_date"], r["block_label"]) for r in blanks),
                         [("2026-10-26", "4:37 pm"), ("2026-10-31", "12:00 pm"), ("2026-11-01", "4:37 pm"),
                          ("2026-11-01", "7:00 pm"), ("2026-11-02", "9:05 am")])
        self.assertTrue(all(r["action_text"] == "" for r in blanks))

    def test_stopped_working_lead_block(self):
        b = by(self.rows, log_date="2026-10-27", block_label="9:15 pm")
        self.assertEqual(b[0]["type"], "break")
        self.assertTrue(b[0]["flags"]["stopped_working"])
        self.assertEqual(b[0]["action_text"], "Stopped working 9:15 (made dinner)")
        self.assertEqual(b[0]["resume_min"], 22 * 60 + 10)
        self.assertEqual([r["action_text"] for r in b[1:]], ["shorten the long sentences"])

    def test_back_without_time_and_stop_at_end(self):
        b = by(self.rows, log_date="2026-10-26", block_label="9:18 am")
        self.assertEqual(b[0]["type"], "break")
        self.assertIsNone(b[0]["resume_min"])
        self.assertNotIn("back", [r["action_text"] for r in b])
        end = by(self.rows, log_date="2026-11-01", block_label="8:05 am")
        self.assertEqual(end[-1]["type"], "break")
        self.assertEqual(end[-1]["action_text"], "stopping work")

    def test_take_a_break_note(self):
        b = by(self.rows, log_date="2026-10-24", block_label="11:04 pm")
        self.assertEqual([r["type"] for r in b], ["action", "break", "action"])

    def test_done_at_is_timing_not_action(self):
        b = by(self.rows, log_date="2026-10-27", block_label="10:49 pm")
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["done_min"], 23 * 60 + 31)

    def test_filled_by_claude_flag(self):
        d27 = by(self.rows, log_date="2026-10-27")
        self.assertTrue(d27 and all(r["flags"]["filled_by_claude"] for r in d27))
        self.assertFalse([r for r in d27 if "filled in by Claude" in r["action_text"]])
        self.assertFalse(any(r["flags"]["filled_by_claude"] for r in by(self.rows, log_date="2026-10-31")))

    def test_untimed_block(self):
        b = [r for r in by(self.rows, log_date="2026-10-31") if r["block_start"] is None]
        self.assertEqual([r["action_text"] for r in b], ["Spent 10 minutes on a snack break",
                                                        "spent 10 more minutes on the bonus list"])
        self.assertEqual(b[0]["block_label"], "after 10:40 am")

    def test_keys_stable_and_unique(self):
        again = P.parse_page(page_fetch_json())["rows"]
        self.assertEqual([r["key"] for r in self.rows], [r["key"] for r in again])
        self.assertEqual(len({r["key"] for r in self.rows}), len(self.rows))
        r = self.rows[0]
        self.assertEqual(r["key"], C.row_key(r["log_date"], r["block_start"], r["position"], r["action_text"]))

    def test_block_index_is_time_order(self):
        d = by(self.rows, log_date="2026-10-27")
        mins = [r["block_min"] for r in d if r["block_min"] is not None]
        self.assertEqual(mins, sorted(mins))


class ClockTests(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(P.resolve_clock((7, 18, None), 18 * 60 + 17)[0], 19 * 60 + 18)
        self.assertEqual(P.resolve_clock((3, 51, None), 15 * 60 + 35)[0], 15 * 60 + 51)
        self.assertEqual(P.resolve_clock((9, 0, None), None)[0], 9 * 60)
        self.assertEqual(P.resolve_clock((2, 0, None), None)[0], 14 * 60)
        m, roll = P.resolve_clock((7, 59, "a"), 19 * 60 + 3)
        self.assertTrue(roll)
        self.assertEqual(m, 1440 + 7 * 60 + 59)
        self.assertEqual(P.resolve_clock((7, 18, None), 23 * 60 + 43), (1440 + 7 * 60 + 18, True))   # next morning
        self.assertEqual(P.resolve_clock((12, 30, "a"), 23 * 60 + 43), (1440 + 30, False))        # same night
        self.assertEqual(P.resolve_clock((12, 5, "p"), 13 * 60 + 17), (12 * 60 + 5, False))       # out of order
        self.assertEqual(P.resolve_clock((8, 0, "a"), 1440 + 9 * 60), (2880 + 8 * 60, True))      # third day

    def test_read_time(self):
        self.assertEqual(P.read_time("10:49 pm/ x")[0], (10, 49, "p"))
        self.assertEqual(P.read_time("1033/ x")[0], (10, 33, None))
        self.assertEqual(P.read_time("12 am / x")[0], (12, 0, "a"))
        self.assertEqual(P.read_time("3:48pm/ x")[0], (3, 48, "p"))
        spec, rest, stop = P.read_time("Stopped working 9:15 (made dinner) / back")
        self.assertEqual(spec, (9, 15, None))
        self.assertTrue(stop)
        self.assertIsNone(P.read_time("3 calls made")[0])


if __name__ == "__main__":
    unittest.main()
