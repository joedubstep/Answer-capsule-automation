import json
import os
import tempfile
import unittest

from tools.inbox_desk import drafts as dr
from tools.inbox_desk import settings as st

LINK = "https://start.example.com/booking-page-1"


class Settings(unittest.TestCase):
    def test_parse_page_text(self):
        text = ("Inbox Desk settings (private)\n- own: other.inbox@example.net\n* client legacy: client.person@example.net\n"
                "- coach Pat Coach: patcoachbiz@example.net, examplecoach.com\n- vendor Example Buyer: buyer.example.com\n"
                "- ignore: friend@example.net\nnot a rule line\n- coach Nobody: no address here\n")
        d = st.parse_settings_text(text)
        self.assertEqual(d["own"], ["other.inbox@example.net"])
        self.assertEqual(d["clients"]["legacy"]["senders"], ["client.person@example.net"])
        self.assertEqual(d["coaches"]["pat_coach"]["label"], "Pat Coach")
        self.assertEqual(d["coaches"]["pat_coach"]["senders"], ["patcoachbiz@example.net", "examplecoach.com"])
        self.assertEqual(d["vendors"]["example_buyer"]["senders"], ["buyer.example.com"])
        self.assertEqual(d["ignore"], ["friend@example.net"])
        self.assertNotIn("nobody", d["coaches"])

    def test_mailto_links_are_read_once(self):
        # Notion stores each address as a mailto link, so the raw line names it twice
        text = ("- own: [other.inbox@example.com](mailto:other.inbox@example.com)\n"
                "- client legacy: [client.person@example.com](mailto:client.person@example.com), example.com\n"
                "- coach Pat Coach: [pat_coach@example.com](mailto:pat_coach@example.com), "
                "<mailto:pat.coach2@example.com>\n"
                "- coach Pat Coach: [pat_coach@example.com](mailto:pat_coach@example.com)\n"
                "- vendor Example Buyer: [Buyer site](https://buyer.example.com/)\n"
                "- ignore: mailto:friend@example.com, [friend@example.com](mailto:friend@example.com)\n"
                "- ignore: *first\\_last@example.com*\n")
        d = st.parse_settings_text(text)
        self.assertEqual(d["own"], ["other.inbox@example.com"])
        self.assertEqual(d["clients"]["legacy"]["senders"], ["client.person@example.com", "example.com"])
        self.assertEqual(d["coaches"]["pat_coach"]["senders"], ["pat_coach@example.com", "pat.coach2@example.com"])
        self.assertEqual(d["vendors"]["example_buyer"]["senders"], ["buyer.example.com"])
        self.assertEqual(d["ignore"], ["friend@example.com", "first_last@example.com"])
        flat = json.dumps(d)
        self.assertNotIn("mailto", flat)
        self.assertNotIn("](", flat)
        # 8 distinct senders: the count says 8, not one per link half
        with tempfile.TemporaryDirectory() as tmp:
            src, out = os.path.join(tmp, "s.md"), os.path.join(tmp, "p.json")
            with open(src, "w") as f:
                f.write(text)
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                st.main(["--from-text", src, "--out", out])
            self.assertIn("settings: 8 sender(s)", buf.getvalue())
        public = {"coaches": {"pat_coach": {"label": "Pat Coach", "domains": [],
                                            "senders": ["pat_coach@example.com"]}}}
        r = st.load_rules(private=d, config={}, senders=public)          # the merge adds each sender once too
        self.assertEqual(r["coaches"]["pat_coach"]["senders"], ["pat_coach@example.com", "pat.coach2@example.com"])

    def test_merge(self):
        cfg = {"google": {"joey_gmail": "owner@example.com"}, "cold_email_domains": ["a-camp.com", "surven.ai"],
               "inbox_desk": {"booking_link": LINK, "client_domains": {"legacy": ["exampleskin.com"]}}}
        priv = st.parse_settings_text("coach Pat Coach: patcoachbiz@example.net, examplecoach.com\nown: o@example.net")
        r = st.load_rules(private=priv, config=cfg)
        self.assertEqual(r["cold_only_domains"], ["a-camp.com"])
        self.assertIn("o@example.net", r["own_addresses"])
        self.assertEqual(r["booking_link"], LINK)
        self.assertIn("exampleskin.com", r["clients"]["legacy"]["domains"])
        self.assertIn("patcoachbiz@example.net", r["coaches"]["pat_coach"]["senders"])
        self.assertIn("examplecoach.com", r["coaches"]["pat_coach"]["domains"])

    def test_cli_prints_counts_not_addresses(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "s.md"), os.path.join(d, "p.json")
            with open(src, "w") as f:
                f.write("coach Pat Coach: patcoachbiz@example.net\n")
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(st.main(["--from-text", src, "--out", out]), 0)
            self.assertNotIn("patcoachbiz", buf.getvalue())
            self.assertTrue(os.path.exists(out))

    def test_repo_senders_have_no_personal_addresses(self):
        import re
        with open(st.SENDERS) as f:
            text = f.read()
        found = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text))
        self.assertEqual(found - {"voice-noreply@google.com", "no-reply@fathom.video"}, set())
        self.assertNotIn("gmail.com", text)


class Drafts(unittest.TestCase):
    def setUp(self):
        self.t = dr.parse_templates()

    def test_all_templates_present(self):
        for k in ("vacancy_or_family_misread", "asked_for_plan", "asked_for_plan_tool", "question_what_is_this",
                  "interested_call", "full", "wrong_person_or_referral", "google_voice", "client", "vendor"):
            self.assertIn(k, self.t)
        for k in ("opt_out", "auto_reply"):
            self.assertNotIn(k, self.t)

    def test_cold_templates_pass_the_copy_checker(self):
        item = {"first": "Pat", "home": "Maple Example House"}
        for k in ("vacancy_or_family_misread", "asked_for_plan", "asked_for_plan_tool", "question_what_is_this",
                  "interested_call", "full", "wrong_person_or_referral"):
            text = dr.fill(self.t[k], item, LINK)
            need = k not in ("full", "wrong_person_or_referral")
            r = dr.check(text, "prospect_email", require_link=need)
            self.assertTrue(r["ok"], (k, r["blocking"]))
            self.assertEqual(r["warnings"], [], (k, r["warnings"]))
            self.assertLessEqual(text.count("?"), 1, k)
            self.assertNotRegex(text, r"\$|\d+\s?%|care home|patients|\bleads?\b|audit", k)

    def test_greeting_and_home_fallback(self):
        text = dr.fill(self.t["vacancy_or_family_misread"], {}, LINK)
        self.assertIn("the open rooms at your home", text)
        # their first name was already in Joey's first email: cold replies open with the point, no greeting
        for k in ("vacancy_or_family_misread", "asked_for_plan", "asked_for_plan_tool", "question_what_is_this",
                  "interested_call", "full", "wrong_person_or_referral"):
            self.assertNotIn("{greeting}", self.t[k], k)
            self.assertNotRegex(self.t[k].split("\n")[0], r"^(Hi|Hello|Hey)\b", k)
        self.assertTrue(dr.fill(self.t["client"], {}, LINK).startswith("Hi,\n"))
        self.assertTrue(dr.fill(self.t["vendor"], {"first": "Pat"}, LINK).startswith("Hi Pat,\n"))

    def test_joeys_rules_the_checker_does_not_cover(self):
        import re
        filler = re.compile(r"\b(fair question|great question|thanks for writing|got it|good to hear|hope this helps)\b", re.I)
        for k in ("vacancy_or_family_misread", "asked_for_plan", "asked_for_plan_tool", "question_what_is_this",
                  "interested_call", "full", "wrong_person_or_referral"):
            text = dr.fill(self.t[k], {"first": "Pat", "home": "Maple Example House"}, LINK)
            self.assertNotRegex(text, filler, k)
            for q in re.findall(r"[^.?\n]*\?", text):  # the ask: 2 to 5 words
                self.assertTrue(2 <= len(q.split()) <= 5, (k, q))
            # the locked result phrase, word for word, wherever Surven's result is named
            if "only thing I do" in text:
                self.assertIn("Filling your empty beds is the only thing I do.", text)
            self.assertNotRegex(text, r"\bfill(ing)? (their|your) open rooms\b", k)

    def test_missing_link_is_held(self):
        text = dr.fill(self.t["interested_call"], {"first": "Pat"}, "")
        self.assertIn(dr.MISSING_LINK, text)
        self.assertFalse(dr.check(text, "prospect_email", require_link=True)["ok"])

    def test_bad_draft_is_blocked(self):
        r = dr.check("Hi Pat \u2014 our clients see 40% more tours. Is now a bad time?", "prospect_email")
        self.assertFalse(r["ok"])
        rules = {b["rule"] for b in r["blocking"]}
        self.assertIn("dash", rules)

    def test_cli(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(dr.fill(self.t["vacancy_or_family_misread"], {"first": "Pat", "home": "Maple"}, LINK))
        try:
            import io
            from contextlib import redirect_stdout
            with redirect_stdout(io.StringIO()):
                self.assertEqual(dr.main(["check", "--file", f.name, "--context", "prospect_email",
                                          "--require-link"]), 0)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
