"""Unit tests for check.py: result shape, severities, fixes, text handling and helpers."""
import re
import unittest

from tools.copy_check import check as cc
from tools.copy_check.check import check
from tools.copy_check.tests.corpus import LONG_HARD

EM = chr(0x2014)


def rules_of(result):
    return [i["rule"] for i in result["issues"]]


class TestShape(unittest.TestCase):
    def test_result_keys(self):
        r = check("Hi Pat " + EM + " thanks.", "prospect_email")
        self.assertEqual(set(r), {"ok", "grade", "context", "counts", "issues"})
        self.assertFalse(r["ok"])
        i = r["issues"][0]
        for k in ("rule", "severity", "match", "line", "fix", "message", "col", "start", "end"):
            self.assertIn(k, i)
        self.assertEqual((i["rule"], i["severity"], i["match"], i["line"]), ("dash", "block", EM, 1))
        self.assertEqual(r["counts"], {"block": 1, "warn": 0})

    def test_empty_text(self):
        r = check("", "prospect_sms")
        self.assertEqual((r["ok"], r["grade"], r["issues"]), (True, None, []))
        r = check(None, "client")
        self.assertTrue(r["ok"])

    def test_ok_ignores_warnings(self):
        r = check("Great to meet you!", "prospect_email")
        self.assertTrue(r["ok"])
        self.assertEqual(rules_of(r), ["exclamation"])
        self.assertEqual(r["counts"], {"block": 0, "warn": 1})

    def test_contexts_and_aliases(self):
        for alias, ctx in (("cold_email", "prospect_email"), ("SMS", "prospect_sms"), (" client ", "client"),
                           ("cold_text", "prospect_sms"), ("internal", "internal")):
            self.assertEqual(check("Hi.", alias)["context"], ctx)
        with self.assertRaises(ValueError):
            check("Hi.", "family")

    def test_issue_order_and_lines(self):
        text = "Hi Pat,\n\nYour care home " + EM + " full.\nIs now a bad time?"
        r = check(text, "client")
        self.assertEqual([(i["rule"], i["line"]) for i in r["issues"]],
                         [("care_home", 3), ("dash", 3), ("bad_time_ask", 4)])
        self.assertEqual(r["issues"][0]["col"], 6)

    def test_whole_text_issues_last(self):
        r = check("Want to talk?", "prospect_email", require_link=True)
        self.assertEqual(r["issues"][-1]["rule"], "missing_link")
        self.assertEqual((r["issues"][-1]["line"], r["issues"][-1]["start"]), (0, None))


class TestSeverity(unittest.TestCase):
    def test_severity_by_context(self):
        self.assertEqual(check("We leverage it.", "client")["issues"][0]["severity"], "block")
        r = check("We leverage it.", "internal")
        self.assertEqual(r["issues"][0]["severity"], "warn")
        self.assertTrue(r["ok"])

    def test_contexts_limit_rules(self):
        self.assertIn("price_before_call", rules_of(check("It is $500.", "prospect_sms")))
        self.assertNotIn("price_before_call", rules_of(check("It is $500.", "client")))
        self.assertIn("care_home", rules_of(check("A care home.", "client")))
        self.assertNotIn("care_home", rules_of(check("A care home.", "internal")))

    def test_grade_block_suppresses_warn(self):
        hard = LONG_HARD
        r = check(hard, "prospect_email")
        self.assertIn("reading_grade_too_high", rules_of(r))
        self.assertNotIn("reading_grade_high", rules_of(r))
        r = check(hard, "client")
        self.assertIn("reading_grade_high", rules_of(r))
        self.assertNotIn("reading_grade_too_high", rules_of(r))

    def test_grade_needs_enough_words(self):
        r = check("Interested in occupancy optimization?", "prospect_sms")
        self.assertGreater(r["grade"], 9)
        self.assertNotIn("reading_grade_too_high", rules_of(r))


class TestFixes(unittest.TestCase):
    def fix(self, text, rule, ctx="client"):
        return [i["fix"] for i in check(text, ctx)["issues"] if i["rule"] == rule][0]

    def test_british_fix_names_us_word(self):
        self.assertIn("inquiry", self.fix("Thanks for the enquiry.", "british_spelling"))
        self.assertIn("color", self.fix("The colour is nice.", "british_spelling"))
        self.assertIn("call you", self.fix("I will ring you.", "british_spelling"))
        self.assertIn("right away", self.fix("I can do it straight away.", "british_spelling"))
        self.assertIn("'realize'", self.fix("I realise it.", "british_ise"))
        self.assertIn("'Organizations'", self.fix("Organisations like yours.", "british_ise"))

    def test_generic_fix(self):
        self.assertEqual(self.fix("We leverage it.", "buzzword"),
                         "Say the plain thing it stands for, in your own words.")


class TestTextHandling(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(cc.normalize("a\r\nb\rc" + chr(0x2028) + "d"), "a\nb\nc\nd")
        self.assertEqual(cc.normalize("a" + chr(0xA0) + "b" + chr(0x202F) + "c" + chr(0xFEFF)), "a b c")

    def test_straighten_keeps_length(self):
        t = chr(0x2018) + "hi" + chr(0x2019) + " " + chr(0x201C) + "x" + chr(0x201D)
        self.assertEqual(cc.straighten(t), "'hi' \"x\"")
        self.assertEqual(len(cc.straighten(t)), len(t))

    def test_curly_quotes_still_match(self):
        self.assertIn("needy_hedge", rules_of(check("Hope you" + chr(0x2019) + "re well.", "prospect_email")))
        r = check("I know you" + chr(0x2019) + "re busy.", "prospect_email")
        self.assertEqual(r["issues"][0]["match"], "I know you" + chr(0x2019) + "re busy")

    def test_split_sentences(self):
        t = "Hi Pat, thanks. Dr. Example came at 3 p.m. today! Is it ok?\n\n- one\n- two\nwrapped\nline"
        got = [t[s:e] for s, e in cc.split_sentences(t)]
        # a bullet that runs on to a lowercase line is one sentence
        self.assertEqual(got, ["Hi Pat, thanks.", "Dr. Example came at 3 p.m. today!", "Is it ok?", "one",
                               "two\nwrapped\nline"])

    def test_time_abbreviation_can_end_a_sentence(self):
        t = "Call at 3 p.m. Does that work? Dr. Example is here. Tour at 9 a.m. on Monday."
        got = [t[s:e] for s, e in cc.split_sentences(t)]
        self.assertEqual(got, ["Call at 3 p.m.", "Does that work?", "Dr. Example is here.",
                               "Tour at 9 a.m. on Monday."])

    def test_blank_links(self):
        t = "See start.example.com/booking-page?x=1 or https://example.com/a?b or pat@example.com now?"
        b = cc.blank_links(t)
        self.assertEqual(len(b), len(t))
        self.assertEqual(b.count("?"), 1)
        self.assertNotIn("example", b)
        self.assertEqual(cc.blank_links("Thanks.Then e.g. 3 p.m. ok"), "Thanks.Then e.g. 3 p.m. ok")

    def test_soft_wrap_vs_new_line(self):
        t = "We help homes\nanswer the phone.\nThanks,\nJoey"
        got = [t[s:e] for s, e in cc.split_sentences(t)]
        self.assertEqual(got, ["We help homes\nanswer the phone.", "Thanks,", "Joey"])

    def test_syllables(self):
        for word, n in (("the", 1), ("room", 1), ("residents", 3), ("family", 3), ("joey", 2), ("have", 1),
                        ("beds", 1), ("before", 2), ("december", 3)):
            self.assertEqual(cc.syllables(word), n, word)

    def test_reading_grade(self):
        g, n = cc.reading_grade("Hi Pat, it's Joey at Surven. Do you have an empty room right now?")
        self.assertEqual(n, 14)
        self.assertAlmostEqual(g, 1.5)
        self.assertEqual(cc.reading_grade("..."), (None, 0))
        self.assertEqual(cc.reading_grade("Yes. No. Ok."), (0.0, 3))

    def test_count_words_treats_names_as_one(self):
        self.assertEqual(cc.count_words("how many rooms are open at Oak Hill Senior Living right now?"), 9)
        self.assertEqual(cc.count_words("Did I miss you the first time?"), 7)
        self.assertEqual(cc.count_words("Hi Pat, Joey here."), 4)

    def test_is_proper(self):
        t = "We met Empower Living. Empower them."
        self.assertTrue(cc.is_proper(t, 7, 14))
        self.assertFalse(cc.is_proper(t, 23, 30))
        self.assertFalse(cc.is_proper("so LEVERAGE it", 3, 11))
        # the first word on a line, after a bullet, a number or an opening quote, is a sentence start
        for t in ("- Leverage it", "  2. Leverage it", "\"Leverage it\"", "Hi.\n* Leverage it", "Ok. (Leverage it)"):
            s = t.index("Leverage")
            self.assertFalse(cc.is_proper(t, s, s + 8), t)
        t = "I saw \"Empower Pines\" there."
        self.assertTrue(cc.is_proper(t, 7, 14))

    def test_word_regex(self):
        self.assertEqual(cc.word_regex("game-changer"), r"\bgame[\s-]+changer\b")
        self.assertEqual(cc.word_regex("enquir*"), r"\benquir\w*\b")
        self.assertEqual(cc.word_regex("re:\\bx\\b"), r"\bx\b")
        for word, hit, miss in (("load bearing", "load-bearing", "loadbearing"), ("tl;dr", "tl;dr", "tldr")):
            rx = re.compile(cc.word_regex(word), re.I | re.A)
            self.assertTrue(rx.search(hit), word)
            self.assertFalse(rx.search(miss), word)

    def test_template_mode_keeps_bad_placeholders(self):
        t = "Hi {{contact.first_name}}, meet [Name] on {date}."
        r = check(t, "client", template=True)
        self.assertEqual([i["match"] for i in r["issues"] if i["rule"] == "merge_field"], ["[Name]", "{date}"])
        r = check(t, "client")
        self.assertEqual(len([i for i in r["issues"] if i["rule"] == "merge_field"]), 3)

    def test_allow_list(self):
        self.assertEqual(check("The ROI is clear. ROI matters. So does roi.", "prospect_email")["issues"], [])


class TestSpeed(unittest.TestCase):
    def test_odd_pastes_stay_fast(self):
        """A 20,000 character paste of odd text must not hang the checker (or the page on Joey's phone)."""
        import time
        from tools.copy_check.tests.corpus import odd_inputs
        for name, text in odd_inputs().items():
            for ctx in ("prospect_sms", "internal"):
                t0 = time.time()
                check(text, ctx, require_link=True, require_optout=True)
                self.assertLess(time.time() - t0, 3.0, "%s in %s is too slow" % (name, ctx))


if __name__ == "__main__":
    unittest.main()
