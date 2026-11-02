import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tools.inbox_desk import classify as cl
from tools.inbox_desk import desk
from tools.inbox_desk import ghl_context as gc
from tools.inbox_desk import settings as st
from tools.inbox_desk.tests import fixtures as fx

HERE = os.path.dirname(os.path.abspath(__file__))
GHL_DIR = os.path.join(HERE, "fixtures", "ghl")
LINK = "https://start.example.com/booking-page-1"
UTC = dt.timezone.utc


def rules(link=LINK):
    r = st.load_rules(private={})
    r["booking_link"] = link
    return r


class Ghl(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GHL_FAKE_DIR": GHL_DIR})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def items(self):
        r = rules()
        a = cl.classify_thread(fx.cold("t1", "We have 2 rooms open."), r)
        b = cl.classify_thread(fx.cold("t2", "Please remove us from your email list", sender="sam@exampleopt.com"), r)
        c = cl.classify_thread(fx.cold("t3", "Yes we have rooms.", sender="chris@exampleanswered.com",
                                       date="2026-11-02T14:00:00Z"), r)
        d = cl.classify_thread(fx.cold("t4", "We have rooms.", sender="new@examplenew.com"), r)
        e = cl.classify_thread(fx.gv("t5", "hi"), r)
        f = cl.classify_thread(fx.cold("t6", "We have 3 rooms.", sender="dana@examplemissed.com",
                                       date="2026-11-02T14:00:00Z"), r)
        return [a, b, c, d, e, f]

    def test_enrich(self):
        items, used = gc.enrich(self.items(), log=lambda *_: None)
        self.assertTrue(used)
        a, b, c, d, e, f = items
        self.assertEqual((a["ghl"]["code"], a["ghl"]["stage"], a["ghl"]["talked"]), ("E24", "Replied", True))
        self.assertEqual(a["action"], "draft_reply")
        self.assertIn("still has code E14", b["cleanup"])
        self.assertIn("open deal at Replied", b["cleanup"])
        self.assertTrue(b["needs_joey"])
        self.assertEqual(c["ghl"]["code"], "E9")
        self.assertTrue(c["ghl"]["answered"])
        self.assertEqual(c["action"], "label_only")
        self.assertEqual(d["ghl"], {"found": False})
        self.assertNotIn("ghl", e)
        # a missed dial after the reply is not an answer: the email draft still gets written
        self.assertEqual(f["ghl"]["code"], "E31")
        self.assertFalse(f["ghl"]["answered"])
        self.assertFalse(f["ghl"]["talked"])
        self.assertEqual(f["action"], "draft_reply")

    def test_no_access_is_skipped(self):
        with mock.patch.dict(os.environ, {"GHL_FAKE_DIR": tempfile.mkdtemp()}):
            msgs = []
            items, used = gc.enrich(self.items(), log=msgs.append)
        self.assertFalse(used)
        self.assertIn("no access", msgs[0])
        self.assertTrue(all("ghl" not in it for it in items))

    def test_cleanup_only_for_live_opt_outs(self):
        self.assertEqual(gc.cleanup_line({"sub": "opt_out"}, {"found": True, "code": "", "deal_status": "lost"}), "")
        self.assertEqual(gc.cleanup_line({"sub": "vacancy_or_family_misread"}, {"found": True, "code": "E1"}), "")


class Names(unittest.TestCase):
    def test_short_home(self):
        self.assertEqual(desk.short_home("Jade Example At Sampletown"), "Jade Example")
        self.assertEqual(desk.short_home("The Example House"), "Example House")
        self.assertEqual(desk.short_home("Maple Example Assisted Living"), "Maple Example")
        self.assertEqual(desk.short_home("Example Place of Sampletown"), "Example Place")
        self.assertEqual(desk.short_home(""), "")


class Guard(unittest.TestCase):
    def test_twin_fires(self):
        # winter (EST, UTC-5): 13 and 21 UTC land on 8am and 4pm
        self.assertEqual(desk.guard(dt.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)), "SKIP")
        self.assertEqual(desk.guard(dt.datetime(2026, 11, 2, 13, 0, tzinfo=UTC)), "RUN")
        self.assertEqual(desk.guard(dt.datetime(2026, 11, 2, 20, 0, tzinfo=UTC)), "SKIP")
        self.assertEqual(desk.guard(dt.datetime(2026, 11, 2, 21, 0, tzinfo=UTC)), "RUN")
        # summer (EDT, UTC-4): 12 and 20 UTC land on 8am and 4pm
        self.assertEqual(desk.guard(dt.datetime(2026, 7, 1, 12, 0, tzinfo=UTC)), "RUN")
        self.assertEqual(desk.guard(dt.datetime(2026, 7, 1, 13, 0, tzinfo=UTC)), "SKIP")
        self.assertEqual(desk.guard(dt.datetime(2026, 7, 1, 20, 0, tzinfo=UTC)), "RUN")
        self.assertEqual(desk.guard(dt.datetime(2026, 7, 1, 21, 0, tzinfo=UTC)), "SKIP")


class Queries(unittest.TestCase):
    def test_scheduled_and_backlog(self):
        r = rules()
        qs = desk.queries("scheduled", r, today=dt.date(2026, 11, 2))
        self.assertEqual([q["name"] for q in qs], ["cold", "voice", "people", "inbox"])
        for q in qs:
            self.assertIn("-label:desk-done", q["query"])
            self.assertIn("after:2026/10/30", q["query"])
        # category:primary returns nothing through the connector, so the Primary tab is "not in the other tabs"
        self.assertNotIn("category:primary", qs[3]["query"])
        for tab in ("promotions", "social", "updates", "forums"):
            self.assertIn("-category:" + tab, qs[3]["query"])
        self.assertIn("getsurven.com", qs[0]["query"])
        self.assertIn("acquisition.com", qs[2]["query"])
        b = desk.queries("backlog", r)
        self.assertEqual(len(b), 1)
        self.assertIn("after:2026/09/23", b[0]["query"])
        self.assertEqual(b[0]["pages"], 4)


class Triage(unittest.TestCase):
    def test_priority_cap_and_skips(self):
        r = rules()
        answered = fx.cold("tA", "Yes we have rooms.")
        answered["messages"].append(fx.msg("tA2", "joey@getsurven.com", "pat@examplehome.com",
                                           "Re: Do you have an open room?", "Thanks", date="2026-11-02T15:00:00Z"))
        answered["messageCount"] = 2
        ts = [fx.thread("n1", fx.msg("n1", "news@example.com", fx.JOEY, "Sale", "x", labels=("INBOX", "CATEGORY_PROMOTIONS"))),
              fx.cold("c1", "2"), fx.gv("g1", "hi"), answered, fx.cold("d1", "We have rooms."),
              fx.thread("k1", fx.msg("k1", "value@acquisition.com", fx.JOEY, "Lesson", "x"))]
        res = desk.triage(fx.search_result(*ts)["threads"], r, max_n=5, draft_threads={"d1"})
        self.assertEqual([x["id"] for x in res["fetch"]], ["c1", "g1", "k1"])
        self.assertEqual([x["id"] for x in res["label_only"]], ["n1", "tA"])
        self.assertEqual(res["label_only"][1]["reason"], "Joey already replied")
        self.assertEqual([x["id"] for x in res["skipped"]], ["d1"])
        self.assertEqual(res["waiting"], 0)
        res = desk.triage(fx.search_result(*ts)["threads"], r, max_n=2, draft_threads={"d1"})
        self.assertEqual([x["id"] for x in res["fetch"]], ["c1", "g1"])
        self.assertEqual(res["waiting"], 3)
        # the full thread (get_thread) shows the reply too
        res = desk.triage([answered], r)
        self.assertEqual(res["label_only"][0]["reason"], "Joey already replied")

    def test_vendor_newsletter_is_not_read(self):
        ts = [fx.thread("v1", fx.msg("v1", "team@datavendor.ai", fx.JOEY, "Up to $500k for your data", "x")),
              fx.thread("v2", fx.msg("v2", "team@polyshares.com", fx.JOEY, "Reminder: finish your intake", "x"))]
        res = desk.triage(fx.search_result(*ts)["threads"], rules())
        self.assertEqual([x["id"] for x in res["fetch"]], ["v2"])
        self.assertEqual([x["id"] for x in res["label_only"]], ["v1"])

    def test_done_label_is_skipped(self):
        t = fx.cold("c1", "2")
        t["messages"][0]["labelIds"].append("Label_99")
        res = desk.triage(fx.search_result(t)["threads"], rules(), done_label_id="Label_99")
        self.assertEqual(res["found"], 0)


class Flow(unittest.TestCase):
    """The whole run on synthetic mail: start, triage, read, classify, skeletons, check, results, digest, labels."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = desk.DIR
        desk.DIR = self.dir
        self.patch = mock.patch.object(desk, "rules", lambda: rules())
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        desk.DIR = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_cmd(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = desk.main(["--dir", self.dir] + list(argv))
        return rc, buf.getvalue()

    def test_full_run(self):
        rc, out = self.run_cmd("start", "--mode", "scheduled")
        self.assertEqual(rc, 0)
        self.assertIn("-label:desk-done", out)
        threads = [fx.cold("c1", "As many as you want."),
                   fx.cold("c2", "yes", quote=fx.PLAN_OFFER, sender="sam@example-two.com"),
                   fx.cold("c3", "Please remove us from your email list", sender="chris@example-three.com"),
                   fx.thread("k1", fx.msg("k1", "value@acquisition.com", fx.JOEY, "The Horse Story", "A lesson.")),
                   fx.thread("a1", fx.msg("a1", fx.JOEY, fx.JOEY, "Follow-up plan for November 2", "plan"))]
        with open(os.path.join(self.dir, "search", "cold-1.json"), "w") as f:
            json.dump(fx.search_result(*threads), f)
        rc, out = self.run_cmd("triage")
        self.assertIn("Read 4, label only 1", out)
        for t in threads[:4]:
            with open(os.path.join(self.dir, "threads", t["id"] + ".json"), "w") as f:
                json.dump(t, f)
        rc, out = self.run_cmd("classify")
        self.assertEqual(rc, 0)
        with open(os.path.join(self.dir, "work.json")) as f:
            work = json.load(f)
        by = {it["thread_id"]: it for it in work["items"]}
        self.assertEqual(by["c1"]["action"], "draft_reply")
        self.assertEqual(by["c2"]["action"], "draft_plan")
        self.assertEqual(by["c3"]["action"], "flag")
        self.assertEqual(by["k1"]["action"], "learning")
        self.assertEqual(by["a1"]["action"], "label_only")
        rc, out = self.run_cmd("skeletons")
        self.assertIn("2 draft(s) written", out)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "plans", "c2.facts.json")))
        rc, out = self.run_cmd("check")
        self.assertEqual(rc, 0, out)
        # a template blank left in is held
        with open(os.path.join(self.dir, "drafts", "c1.txt"), "a") as f:
            f.write("\n{home}\n")
        rc, out = self.run_cmd("check")
        self.assertEqual(rc, 1)
        self.assertIn("template_blank", out)
        self.run_cmd("result", "c1", "drafted", "--draft-id", "r-1")
        self.run_cmd("result", "c2", "plan_drafted", "--draft-id", "r-2")
        self.run_cmd("result", "k1", "learning_saved")
        self.run_cmd("result", "c3", "no_action")
        rc, out = self.run_cmd("result", "c3", "bogus")
        self.assertEqual(rc, 2)
        rc, out = self.run_cmd("digest")
        self.assertIn("DIGEST to " + fx.JOEY, out)
        with open(os.path.join(self.dir, "digest.json")) as f:
            d = json.load(f)
        self.assertEqual(d["to"], fx.JOEY)
        self.assertTrue(d["subject"].startswith("Inbox Desk: 2 drafts ready (Maple Example House, "), d["subject"])
        self.assertIn("plan)", d["subject"])
        self.assertIn("Saved to Learnings: Acquisition.com.", d["body"])
        self.assertIn("Send it from joey@", d["body"])
        self.assertNotRegex(d["subject"] + d["body"], "[\u2013\u2014]")
        rc, out = self.run_cmd("labels")
        self.assertEqual(set(out.split()), {"c1", "c2", "c3", "k1", "a1"})

    def test_dry_run_and_stale_files(self):
        with open(os.path.join(self.dir, "digest.json"), "w") as f:
            json.dump({"to": "x", "subject": "old", "body": "old"}, f)
        rc, out = self.run_cmd("start", "--dry-run")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "digest.json")))
        with open(os.path.join(self.dir, "search", "cold-1.json"), "w") as f:
            json.dump(fx.search_result(fx.cold("c1", "2")), f)
        self.run_cmd("triage")
        with open(os.path.join(self.dir, "threads", "c1.json"), "w") as f:
            json.dump(fx.cold("c1", "2"), f)
        self.run_cmd("classify")
        self.run_cmd("result", "c1", "drafted", "--draft-id", "r-1")
        rc, out = self.run_cmd("digest")
        self.assertIn("DRY RUN: do not send", out)
        rc, out = self.run_cmd("labels")
        self.assertIn("DRY RUN: do not label", out)
        self.assertNotIn("c1\n", out)

    def test_nothing_new(self):
        self.run_cmd("start")
        with open(os.path.join(self.dir, "search", "cold-1.json"), "w") as f:
            json.dump({}, f)
        rc, out = self.run_cmd("triage")
        self.assertIn("NOTHING NEW", out)
        self.run_cmd("classify")
        rc, out = self.run_cmd("digest")
        self.assertIn("NO DIGEST", out)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "digest.txt")))

    def test_unread_thread_is_not_labeled(self):
        self.run_cmd("start")
        with open(os.path.join(self.dir, "search", "cold-1.json"), "w") as f:
            json.dump(fx.search_result(fx.cold("c9", "2")), f)
        self.run_cmd("triage")
        self.run_cmd("classify")
        rc, out = self.run_cmd("labels")
        self.assertEqual(out.strip(), "(none)")

    def test_digest_needs_you_lines(self):
        work = {"booking_link_set": False, "items": [
            {"thread_id": "o1", "class": "cold_reply", "sub": "opt_out", "action": "flag", "require_link": False,
             "cleanup": "E14 opted out but still has code E14 in GHL. Mark the deal lost.", "from_domain": "x.com"},
            {"thread_id": "m1", "class": "client", "sub": "message", "action": "draft_reply", "label": "AGC",
             "reply_mode": "copy_to_ghl", "require_link": False},
            {"thread_id": "v1", "class": "vendor_or_data_sale", "sub": "system", "action": "summarize",
             "label": "Polyshares", "needs_joey": True},
            {"thread_id": "q1", "class": "cold_reply", "sub": "interested_call", "action": "draft_reply",
             "require_link": True, "home": "Maple"}]}
        res = {"m1": {"done": "drafted"}, "v1": {"done": "summarized", "note": "they asked for intake changes"},
               "q1": {"done": "failed", "note": "copy check held it"}}
        d = desk.digest(work, res, fx.JOEY)
        self.assertEqual(d["to"], fx.JOEY)
        self.assertTrue(d["subject"].startswith("Inbox Desk: 5 need"), d["subject"])
        self.assertIn("Copy it into the conversation in GoHighLevel", d["body"])
        self.assertIn("Polyshares: they asked for intake changes", d["body"])
        self.assertIn("booking link", d["body"])
        self.assertIsNone(desk.digest({"items": [{"thread_id": "n", "class": "noise", "sub": "bulk",
                                                  "action": "label_only"}]}, {}, fx.JOEY))


if __name__ == "__main__":
    unittest.main()
