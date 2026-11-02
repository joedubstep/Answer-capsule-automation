import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from tools.inbox_desk import classify as cl
from tools.inbox_desk import settings as st
from tools.inbox_desk.tests import fixtures as fx

PRIVATE = {"own": ["owner.other@example.net"],
           "clients": {"legacy": {"label": "Legacy client", "senders": ["client.person@example.net"]}},
           "coaches": {"pat_coach": {"label": "Pat Coach", "senders": ["patcoachbiz@example.net"]}},
           "vendors": {}, "ignore": ["friend@example.net"]}


def R(private=None):
    return st.load_rules(private=PRIVATE if private is None else private)


def sub_of(body, **kw):
    return cl.classify_thread(fx.cold("t1", body, **kw), R())


class ColdSubclass(unittest.TestCase):
    def check(self, body, want, **kw):
        it = sub_of(body, **kw)
        self.assertEqual(it["class"], "cold_reply", body)
        self.assertEqual(it["sub"], want, f"{body!r} -> {it['sub']} ({it['reasons']})")
        return it

    def test_vacancy_and_family_misread(self):
        for b in ("As many as you want.", "2", "Yes we have rooms available.",
                  "We currently have a waiting list for long-term placement and have 1 skilled bed open.",
                  "Joey I'm filling up quickly but I do have rooms available. Price dependent on private or shared.",
                  "We have rooms available, are you looking for Memory Care or Assisted Living?",
                  "Thank you for reaching out currently we have one room opening up in November. Please feel free "
                  "to reach out to Sam Sample for further details.",
                  "We have a few open units and would love to do a tour as soon as possible."):
            self.check(b, "vacancy_or_family_misread")

    def test_rooms_number_kept(self):
        it = self.check("2", "vacancy_or_family_misread", quote=fx.NUDGE)
        self.assertEqual(it["rooms"], 2)
        self.assertEqual(it["action"], "draft_reply")
        self.assertTrue(it["require_link"])
        self.assertEqual(it["copy_context"], "prospect_email")

    def test_asked_for_plan(self):
        self.check("Yes please I would like to see your plan", "asked_for_plan", quote=fx.PLAN_OFFER)
        self.check("yes", "asked_for_plan", quote=fx.PLAN_OFFER)
        self.check("I would like for you to send it", "asked_for_plan", quote=None)
        it = self.check("Sure, yes.", "asked_for_plan", quote=fx.TOOL_OFFER)
        self.assertEqual(it["template"], "asked_for_plan_tool")
        self.assertEqual(it["action"], "draft_plan")

    def test_yes_to_rooms_is_not_a_plan(self):
        self.check("Yes", "vacancy_or_family_misread", quote=fx.ROOMS_Q)

    def test_question_what_is_this(self):
        for b in ("May I know what this is about?", "What is this regarding?", "Who is this?",
                  "My office manager said she got an email from you, asking if we had an open room.\n\n"
                  "Do we have a contract with your company?"):
            self.check(b, "question_what_is_this")

    def test_unclear_is_low_confidence_question(self):
        it = self.check("Thanks, Joey. I'll take a look.", "question_what_is_this", quote=fx.NUDGE)
        self.assertEqual(it["confidence"], "low")

    def test_interested_call(self):
        for b in ("Sure, call me tomorrow at 2. My cell is 555-010-0000.", "How much does it cost?",
                  "Tell me more about how this works."):
            self.check(b, "interested_call")

    def test_full_and_not_interested(self):
        it = self.check("Hi Joey,\n\nThank you for reaching out. Currently, we have no availability at Example House."
                        "\n\nMany thanks,\nPat Example", "not_interested_or_full")
        self.assertEqual((it["kind"], it["template"], it["action"]), ("full", "full", "draft_reply"))
        self.assertFalse(it["require_link"])
        it = self.check("No, we don't have any rooms right now.", "not_interested_or_full")
        self.assertEqual(it["kind"], "full")
        it = self.check("Not interested, thanks.", "not_interested_or_full")
        self.assertEqual((it["kind"], it["action"]), ("not_interested", "label_only"))

    def test_opt_out(self):
        for b in ("Please remove us from your email list, OK?", "No", "Unsubscribe"):
            it = self.check(b, "opt_out")
            self.assertEqual(it["action"], "flag")
            self.assertEqual(it["reply_to"], "")

    def test_wrong_person(self):
        for b in ("Pat is no longer with Maple Example House. Thank you, Sam", "I'm not the right person for this.",
                  "I have forwarded your email to our director."):
            it = self.check(b, "wrong_person_or_referral")
            self.assertFalse(it["require_link"])

    def test_auto_reply(self):
        self.check("I am out of the office, returning on Tuesday.", "auto_reply", quote=None,
                   subject="Automatic reply: Do you have an open room?")
        self.check("Hello, I am currently out of the office. I will be back at my desk on Monday.", "auto_reply",
                   quote=None, subject="Out of Office: 10/30/26")
        self.check("Thank you for reaching out to our Compliance Team. You can expect a response within two days.",
                   "auto_reply", quote=None, subject="Ticket# 00000001: Do you have an open room?",
                   sender="salesforce_noreply@example.com", to=fx.SHARED_TO)
        it = self.check("", "auto_reply", quote=fx.NUDGE)
        self.assertEqual(it["kind"], "empty")

    def test_outlook_quote_and_names(self):
        it = self.check("We have 1 bed open.\n\nPat Example\nAdministrator\nMaple Example Assisted Living",
                        "vacancy_or_family_misread", style="outlook", quote=fx.NUDGE)
        self.assertEqual(it["first"], "Pat")
        self.assertEqual(it["home"], "Maple Example Assisted Living")

    def test_home_from_quote(self):
        it = self.check("As many as you want.", "vacancy_or_family_misread")
        self.assertEqual(it["home"], "Maple Example House")
        self.assertEqual(it["reply_subject"], "Re: Do you have an open room?")
        self.assertEqual(it["reply_to"], "pat@examplehome.com")


class ColdDetection(unittest.TestCase):
    def test_shared_domain_needs_campaign_signal(self):
        t = fx.thread("t", fx.msg("t", "workspace-noreply@google.com", fx.SHARED_TO, "Your recommendations",
                                  "Add team members", labels=("INBOX", "CATEGORY_UPDATES")))
        self.assertEqual(cl.classify_thread(t, R())["class"], "noise")
        t = fx.cold("t2", "Yes", to=fx.SHARED_TO)
        self.assertEqual(cl.classify_thread(t, R())["class"], "cold_reply")

    def test_cold_only_domain_new_subject(self):
        t = fx.thread("t", fx.msg("t", "pat@examplehome.com", "joey@survenoccupancy.com", "Maple Example House",
                                  "Do we have a contract with your company?"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["sub"]), ("cold_reply", "question_what_is_this"))

    def test_bulk_to_cold_only_is_not_a_reply(self):
        t = fx.thread("t", fx.msg("t", "news@example-vendor.com", "joey@trysurven.com", "Our fall sale",
                                  "Big savings", labels=("INBOX", "CATEGORY_PROMOTIONS")))
        self.assertNotEqual(cl.classify_thread(t, R())["class"], "cold_reply")

    def test_joey_already_answered(self):
        t = fx.cold("t", "Yes we have rooms.")
        t["messages"].append(fx.msg("t2", "joey@getsurven.com", "pat@examplehome.com", "Re: Do you have an open room?",
                                    "Thanks Pat.", date="2026-11-02T15:00:00Z"))
        t["messageCount"] = 2
        it = cl.classify_thread(t, R())
        self.assertTrue(it["answered"])
        self.assertEqual(it["action"], "label_only")


class SearchPreview(unittest.TestCase):
    def test_preview_without_body(self):
        res = fx.search_result(fx.cold("p1", "2"), fx.cold("p2", "back Monday", quote=None,
                                                             subject="Automatic reply: Do you have an open room?"))
        a, b = [cl.classify_thread(t, R()) for t in res["threads"]]
        self.assertEqual((a["sub"], a["action"]), ("not_read", "read"))
        self.assertEqual((b["sub"], b["action"]), ("auto_reply", "label_only"))

    def test_bulk_subdomain(self):
        t = fx.thread("s1", fx.msg("s1", "pat@updates.example-saas.com", "hello@surven.ai", "We launched", "x"))
        self.assertEqual(cl.classify_thread(t, R())["sub"], "bulk")


class OtherClasses(unittest.TestCase):
    def test_google_voice_person_and_own_line(self):
        it = cl.classify_thread(fx.gv("g1", "Is the room still open?"), R())
        self.assertEqual((it["class"], it["sub"], it["action"], it["reply_mode"]),
                         ("google_voice_text", "person", "draft_reply", "gv_sms"))
        self.assertEqual(it["text"], "Is the room still open?")
        self.assertEqual(it["copy_context"], "prospect_sms")
        it = cl.classify_thread(fx.gv("g2", "What's the price", own=True), R())
        self.assertEqual((it["sub"], it["action"], it["reply_to"]), ("own_line", "label_only", ""))

    def test_client_relay_message_and_automation_copy(self):
        t = fx.thread("c1", fx.msg("c1", "office@mg.americangoldencare.com", fx.JOEY,
                                   "RE: [External]Re: Resource database", "Thanks for your reply. Pat"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["sub"], it["reply_mode"], it["reply_to"]),
                         ("client", "message", "copy_to_ghl", ""))
        t = fx.thread("c2", fx.msg("c2", "office@splendorresidencehome.com", "office@example.net", "Your visit is set",
                                   "See you soon"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["sub"], it["action"]), ("client", "automation_copy", "label_only"))

    def test_private_client_sender(self):
        t = fx.thread("c3", fx.msg("c3", "client.person@example.net", fx.JOEY, "Question about posts", "Can we talk?"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["label"], it["reply_mode"]), ("client", "Legacy client", "email"))
        self.assertEqual(cl.classify_thread(t, R(private={}))["class"], "noise")

    def test_coach(self):
        t = fx.thread("k1", fx.msg("k1", "value@acquisition.com", fx.JOEY, "Your New Scaling Frameworks", "Lesson"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["action"], it["label"]), ("coach", "learning", "Acquisition.com"))
        self.assertEqual(it["learning"]["Source"], "Acquisition.com")
        self.assertEqual(it["learning"]["Applied"], "__NO__")
        t = fx.thread("k2", fx.msg("k2", "coach.desk@seniorlivingmastery.com", fx.JOEY, "Fwd: Census software", "x"))
        self.assertEqual(cl.classify_thread(t, R())["class"], "coach")

    def test_coach_from_private_list_and_recap(self):
        t = fx.thread("k3", fx.msg("k3", "patcoachbiz@example.net", fx.JOEY, "Notes from our call", "Do this"))
        self.assertEqual(cl.classify_thread(t, R())["class"], "coach")
        t = fx.thread("k4", fx.msg("k4", "no-reply@fathom.video", fx.JOEY, "Recap of your meeting with Pat Coach", "x"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["sub"]), ("coach", "call_recap"))
        t = fx.thread("k5", fx.msg("k5", "no-reply@fathom.video", fx.JOEY, "Recap of your meeting with Sam Sample", "x"))
        self.assertEqual(cl.classify_thread(t, R())["class"], "noise")
        t = fx.thread("k6", fx.msg("k6", "patcoachbiz@example.net", fx.JOEY,
                                   "Invitation: Joey and Pat Coach @ Wed Nov 4", "x"))
        self.assertEqual(cl.classify_thread(t, R())["class"], "noise")

    def test_vendor(self):
        t = fx.thread("v1", fx.msg("v1", "advisor@simpleclosure.com", fx.SHARED_TO, "Re: Asset Hub next step", "Hi"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["sub"], it["action"], it["template"]),
                         ("vendor_or_data_sale", "person", "draft_reply", "vendor"))
        t = fx.thread("v2", fx.msg("v2", "team@polyshares.com", fx.JOEY, "Changes requested on your intake", "x"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["sub"], it["action"], it["needs_joey"]), ("system", "summarize", True))
        t = fx.thread("v3", fx.msg("v3", "team@datavendor.ai", fx.JOEY, "Up to $500k for your data", "x"))
        self.assertEqual(cl.classify_thread(t, R())["action"], "label_only")

    def test_automation_alerts(self):
        t = fx.thread("a1", fx.msg("a1", fx.JOEY, fx.JOEY, "MORNING SALES BRIEF: NOV $0", "brief"))
        self.assertEqual(cl.classify_thread(t, R())["class"], "automation_alert")
        t = fx.thread("a2", fx.msg("a2", fx.JOEY, fx.JOEY, "Data sale: new messages", "x"))
        self.assertEqual(cl.classify_thread(t, R())["class"], "automation_alert")
        t = fx.thread("a3", fx.msg("a3", "alerts@mail.msgsndrdeliver.com", "office@example.net", "New Booking!", "x"))
        self.assertEqual(cl.classify_thread(t, R())["sub"], "lead_alert")

    def test_noise_and_unknown_person(self):
        t = fx.thread("n1", fx.msg("n1", "messages-noreply@linkedin.com", fx.JOEY, "Add a contact", "x",
                                   labels=("INBOX", "CATEGORY_SOCIAL")))
        self.assertEqual(cl.classify_thread(t, R())["sub"], "bulk")
        t = fx.thread("n2", fx.msg("n2", "sam.sample@example.org", fx.JOEY, "Quick question", "Are you free Friday?"))
        it = cl.classify_thread(t, R())
        self.assertEqual((it["class"], it["sub"], it["action"], it["needs_joey"]),
                         ("noise", "unknown_person", "summarize", True))
        t = fx.thread("n3", fx.msg("n3", "friend@example.net", fx.JOEY, "Lunch", "Lunch?"))
        self.assertEqual(cl.classify_thread(t, R())["sub"], "ignored")
        t = fx.thread("n4", fx.msg("n4", "edu@example.org", fx.JOEY, "Invitation: Meet @ Wed", "x"))
        self.assertEqual(cl.classify_thread(t, R())["sub"], "bulk")


class Cli(unittest.TestCase):
    def test_files_and_counts(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.json"), "w") as f:
                json.dump(fx.search_result(fx.cold("x1", "2"), fx.gv("x2", "hi")), f)
            with open(os.path.join(d, "b.json"), "w") as f:
                json.dump(fx.cold("x3", "Please remove us from your email list"), f)
            with open(os.path.join(d, "private.json"), "w") as f:
                json.dump({}, f)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cl.main([os.path.join(d, "a.json"), os.path.join(d, "b.json"), "--private",
                              os.path.join(d, "private.json")])
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("counts:", out)
        self.assertIn("cold_reply/opt_out 1", out)
        self.assertIn("google_voice_text/person 1", out)
        self.assertNotIn("examplehome.com>", out)


if __name__ == "__main__":
    unittest.main()
