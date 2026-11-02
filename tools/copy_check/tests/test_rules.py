"""rules.json is well formed, covers Joey's locked rules, and its own words follow them."""
import re
import unittest

from tools.copy_check.check import CONTEXTS, KINDS, METRICS, SEVERITIES, check, compile_rules, load_rules, rx

RAW = load_rules()
COMPILED = compile_rules(RAW)
BY_ID = {r["id"]: r for r in RAW["rules"]}

# Every rule the build spec and Joey's locked rules call for.
REQUIRED = [
    "dash", "buzzword", "british_spelling", "british_ise", "care_home", "patients", "leads_for_families",
    "cold_outreach_words", "bad_time_ask", "price_before_call", "emoji",
    "tldr", "idiom", "needy_hedge", "merge_field", "lowercase_start", "long_sentence", "reading_grade_high",
    "reading_grade_too_high", "multi_question", "exclamation", "missing_link", "missing_optout",
]
LOCKED_BUZZWORDS = ["pulse", "load bearing", "same breath", "leverage", "unlock", "double down", "synergy",
                    "ecosystem", "journey", "robust", "seamless", "game-changer", "level up", "deep dive",
                    "circle back", "bandwidth", "granular", "holistic"]


def all_patterns(r):
    pats = [(p["re"], p["flags"]) for p in r.get("_res", [])]
    if r["kind"] == "metric" and r.get("pattern"):
        pats.append((r["pattern"], "i"))
    if r.get("template_ok"):
        pats.append((r["template_ok"], "i"))
    pats += [(s["pattern"], s.get("flags", "i")) for s in r.get("skip_if", [])]
    pats += [("(?:%s)" % e["re"], "i") for e in r.get("_entries", [])]
    if r.get("suggest"):
        pats.append((r["suggest"][0], "i"))
    if r.get("before"):
        pats.append((r["before"], ""))
    return pats


class TestSchema(unittest.TestCase):
    def test_top_level(self):
        self.assertEqual(set(RAW["contexts"]), set(CONTEXTS))
        self.assertTrue(RAW["version"])

    def test_ids_unique_and_labeled(self):
        ids = [r["id"] for r in RAW["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        for r in RAW["rules"]:
            self.assertRegex(r["id"], r"^[a-z][a-z0-9_]*$")
            self.assertTrue(r.get("label"), r["id"])

    def test_fields(self):
        for r in RAW["rules"]:
            with self.subTest(rule=r["id"]):
                self.assertIn(r["severity"], SEVERITIES)
                self.assertIn(r["kind"], KINDS)
                self.assertTrue(r["contexts"])
                self.assertTrue(set(r["contexts"]) <= set(CONTEXTS))
                for ctx, sev in (r.get("severity_by_context") or {}).items():
                    self.assertIn(ctx, r["contexts"])
                    self.assertIn(sev, SEVERITIES)
                self.assertTrue(r["message"].strip() and r["fix"].strip())
                if r["kind"] == "regex":
                    self.assertTrue(r.get("pattern") or r.get("patterns"))
                elif r["kind"] == "wordlist":
                    self.assertTrue(r["words"])
                else:
                    self.assertIn(r["metric"], METRICS)
                if r.get("suppressed_by"):
                    self.assertIn(r["suppressed_by"], BY_ID)

    def test_patterns_compile_and_never_match_empty(self):
        for r in COMPILED["rules"]:
            for src, flags in all_patterns(r):
                with self.subTest(rule=r["id"], pattern=src[:60]):
                    self.assertIsNone(rx(src, flags).fullmatch(""), "pattern can match empty text")

    def test_js_safe_syntax(self):
        """No Python-only regex syntax: lookbehind, inline flags, named groups, \\A \\Z, possessive."""
        bad = re.compile(r"\(\?<[=!]|\(\?[aiLmsux]+\)|\(\?P<|\\[AZ]|[*+?]\+")
        for r in COMPILED["rules"]:
            for src, _ in all_patterns(r):
                self.assertIsNone(bad.search(src), "%s: %s" % (r["id"], src[:80]))

    def test_no_word_in_two_lists(self):
        seen = {}
        for r in RAW["rules"]:
            if r["kind"] != "wordlist":
                continue
            for w in r["words"]:
                key = (w["w"] if isinstance(w, dict) else w).lower().replace("-", " ")
                self.assertNotIn(key, seen, "%r is in %s and %s" % (key, seen.get(key), r["id"]))
                seen[key] = r["id"]


class TestCoverage(unittest.TestCase):
    def test_required_rules_present(self):
        self.assertEqual([i for i in REQUIRED if i not in BY_ID], [])

    def test_locked_buzzwords(self):
        words = [w.lower() for w in BY_ID["buzzword"]["words"]]
        for w in LOCKED_BUZZWORDS:
            self.assertIn(w, words)
        self.assertIn("ROI", BY_ID["buzzword"]["allow"])
        for w in LOCKED_BUZZWORDS:
            self.assertIn("buzzword", [i["rule"] for i in check("We " + w + " here.", "client")["issues"]], w)

    def test_locked_british_words(self):
        for w in ("enquiry", "enquiries", "organise", "organisation", "realise", "colour", "favour", "behaviour",
                  "centre", "whilst", "amongst", "learnt", "practise", "licence", "defence", "grey", "cancelled",
                  "speciality", "ring you", "straight away"):
            got = [i["rule"] for i in check("Thanks, " + w + " here.", "internal")["issues"]]
            self.assertTrue({"british_spelling", "british_ise"} & set(got), w)
        for w in ("realistic", "organism", "cancellation", "specialist", "license", "gray", "center", "ring"):
            got = [i["rule"] for i in check("Thanks, " + w + " here.", "internal")["issues"]]
            self.assertFalse({"british_spelling", "british_ise"} & set(got), w)

    def test_cold_words_whole_word_only(self):
        for w in ("scoreboard", "gradual", "upgrade", "scorecard", "auditorium"):
            got = [i["rule"] for i in check("The " + w + " is here.", "prospect_email")["issues"]]
            self.assertNotIn("cold_outreach_words", got, w)
        for w in ("audit", "assessment", "grade", "score", "Scores", "graded"):
            got = [i["rule"] for i in check("The " + w + " is here.", "prospect_email")["issues"]]
            self.assertIn("cold_outreach_words", got, w)


class TestOwnWords(unittest.TestCase):
    def test_messages_and_fixes_follow_the_rules(self):
        """The checker's own messages are plain US English with no dashes."""
        for r in RAW["rules"]:
            for field in ("message", "fix", "label"):
                res = check(r[field], "internal")
                bad = [i["rule"] for i in res["issues"]
                       if i["rule"] in ("dash", "british_spelling", "british_ise", "tldr") and i["rule"] != r["id"]]
                self.assertEqual(bad, [], "%s.%s" % (r["id"], field))

    def test_no_literal_dashes_in_rules_file(self):
        with open("tools/copy_check/rules.json", encoding="utf-8") as f:
            text = f.read()
        self.assertFalse(any(c in text for c in (chr(0x2012), chr(0x2013), chr(0x2014), chr(0x2015))))


if __name__ == "__main__":
    unittest.main()
