import unittest

from tools.inbox_desk import textutil as tu


class SplitReply(unittest.TestCase):
    def test_gmail_on_wrote(self):
        new, quoted = tu.split_reply("As many as you want.\n\nOn Thu, Oct 29, 2026, 7:25 AM Surven Occupancy "
                                     "<joey@example-campaign.com> wrote:\n\n> Hi Pat, how many rooms are open?")
        self.assertEqual(new, "As many as you want.")
        self.assertIn("how many rooms", quoted)

    def test_wrapped_on_line(self):
        new, _ = tu.split_reply("Yes.\n\nOn Wed, Sep 30, 2026 at 9:00 AM Surven <joey@\nexample.ai> wrote:\n> hi")
        self.assertEqual(new, "Yes.")

    def test_outlook_header_block(self):
        new, quoted = tu.split_reply("We have 1 bed open.\n\n________________________________\n\nFrom: Surven "
                                     "<joey@example.com>\nSent: Saturday\n\nHey, I just emailed you.")
        self.assertEqual(new, "We have 1 bed open.")
        self.assertIn("I just emailed you", quoted)

    def test_inline_original_message(self):
        new, quoted = tu.split_reply("Thanks for your reply. Pat Example pat@example.org -----Original Message----- "
                                     "From: Joey Sent: Friday To: Pat Subject: Hi")
        self.assertTrue(new.startswith("Thanks for your reply."))
        self.assertNotIn("Original Message", new)
        self.assertIn("Original Message", quoted)

    def test_inline_from_sent(self):
        new, _ = tu.split_reply("Sounds good. From: Surven Occupancy Sent: Friday, October 23 To: Pat")
        self.assertEqual(new, "Sounds good.")

    def test_angle_quote_lines(self):
        new, _ = tu.split_reply("2\n> On Oct 29, 2026, at 9:08 AM, Surven wrote:\n> Hi")
        self.assertEqual(new, "2")

    def test_only_quote_is_empty(self):
        new, _ = tu.split_reply("On Wed, Oct 28, 2026 at 7:41 AM Surven Occupancy <joey@x.com> wrote:\n\n> Hey")
        self.assertEqual(new, "")


class Signature(unittest.TestCase):
    def test_name_block_after_blank_line(self):
        body, sig = tu.split_signature("I do have rooms available.\n\nPat Example\nAdministrator\nMaple Example House\n"
                                       "(555) 010-0000 Main")
        self.assertEqual(body, "I do have rooms available.")
        self.assertTrue(sig.startswith("Pat Example"))

    def test_closing_line(self):
        body, sig = tu.split_signature("Hi Joey,\n\nWe are full.\n\nMany thanks,\n*Pat Example*\n*Owner*")
        self.assertNotIn("Many thanks", body)
        self.assertIn("Pat Example", sig)

    def test_legal_notice(self):
        body, sig = tu.split_signature("Yes we have rooms.\nThis message is confidential and intended only for you.")
        self.assertEqual(body, "Yes we have rooms.")
        self.assertEqual(tu.trim_legal(sig), "")

    def test_no_signature(self):
        body, sig = tu.split_signature("Thanks, Joey. I'll take a look.")
        self.assertEqual((body, sig), ("Thanks, Joey. I'll take a look.", ""))

    def test_double_dash(self):
        body, sig = tu.split_signature("2\n\n--\nExample Holdings LLC\nMaple Example House")
        self.assertEqual(body, "2")


class Facts(unittest.TestCase):
    def test_opt_out(self):
        for t in ("Please remove us from your email list, OK?", "No", "no thanks", "Unsubscribe",
                  "Stop emailing me", "Do not email us again"):
            self.assertTrue(tu.is_opt_out(t), t)
        for t in ("No longer with the company", "No, we don't have any rooms right now.", "Yes we have rooms",
                  "Not sure what this is", "No problem, call me"):
            self.assertFalse(tu.is_opt_out(t), t)

    def test_room_count(self):
        self.assertEqual(tu.room_count("2"), 2)
        self.assertEqual(tu.room_count("3 rooms"), 3)
        self.assertEqual(tu.room_count("We have one room opening up in November"), 1)
        self.assertEqual(tu.room_count("have 1 skilled bed open"), 1)
        self.assertIsNone(tu.room_count("Call me at (555) 010-0000"))
        self.assertIsNone(tu.room_count("As many as you want."))

    def test_home_from_campaign_quote(self):
        pats = ["(?:open rooms|rooms are open|rooms open) at (?P<home>[^?\\n]{2,80}?) right now"]
        self.assertEqual(tu.home_guess("> Hi Pat, how many rooms are open at Maple Example House\n> right now?", "",
                                       pats)[0], "Maple Example House")
        self.assertEqual(tu.home_guess("> do you have any open rooms at Example House, The right now?", "", pats)[0],
                         "Example House")

    def test_home_from_signature(self):
        self.assertEqual(tu.home_guess("", "Pat Example\nAdministrator\nMaple Example Assisted Living\n(555) 010-0000",
                                       [])[0], "Maple Example Assisted Living")

    def test_first_name(self):
        self.assertEqual(tu.first_name_guess("Yes.", "Pat Example\nAdministrator")[0], "Pat")
        self.assertEqual(tu.first_name_guess("Yes.", "Many thanks,\n*Pat Example*")[0], "Pat")
        self.assertEqual(tu.first_name_guess("Yes.", "", "Pat", "pat.example@example.com")[0], "Pat")
        self.assertIsNone(tu.first_name_guess("Yes.", "", "Pat", "office@example.com")[0])
        self.assertIsNone(tu.first_name_guess("Yes.", "Administrator\nMaple Example House")[0])
        self.assertIsNone(tu.first_name_guess("2", "Example Legacy Health Services LLC\nMaple Example Assisted Living")[0])
        self.assertEqual(tu.first_name_guess("x", "Thank you,\n\nPat Example, *Executive Director*")[0], "Pat")

    def test_gv_footer(self):
        t = tu.strip_footer("<https://voice.google.com>\nWhat's the price\nTo respond to this text message, reply",
                            ["to respond to this text message"])
        self.assertEqual(t, "What's the price")

    def test_html_body(self):
        t = tu.body_of({"htmlBody": "<div>Yes please</div><blockquote>old</blockquote>"})
        self.assertIn("Yes please", t)
        self.assertNotIn("old", t)

    def test_shorten_links(self):
        self.assertEqual(tu.shorten_links("see https://e.example.com/" + "x" * 90), "see [link]")


if __name__ == "__main__":
    unittest.main()
