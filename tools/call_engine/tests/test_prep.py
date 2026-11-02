import datetime as dt
import json
import os
import shutil
import tempfile
import unittest

from tools.call_engine import prep

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
DAY = dt.date(2026, 11, 3)


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def read_abs(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def ghl_raw():
    evs = json.loads(read(os.path.join("ghl", "calendars__events.json")))["events"]
    keys = {"siNHUDan1hhV6eKLstdq": "discovery_call", "wT88OYdr5mJs0nG5ohXU": "client_calls"}
    return [dict(e, _calendar_key=keys[e["calendarId"]]) for e in evs]


class FakeGHL(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("GHL_FAKE_DIR")
        os.environ["GHL_FAKE_DIR"] = os.path.join(FIX, "ghl")
        self.tmp = tempfile.mkdtemp(prefix="call_engine_test_")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GHL_FAKE_DIR", None)
        else:
            os.environ["GHL_FAKE_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class MatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = prep.load_config()
        cls.res = prep.match(json.loads(read("gcal_day.json")), DAY, cfg, ghl_raw(),
                             prep.parse_existing(read("call_prep_page.json")), ["owner@surven.ai"])

    def test_calls_found_and_deduped(self):
        got = [(c["time_et"], c["kind"], c["name"]) for c in self.res["calls"]]
        self.assertEqual(got, [("10:00 AM", "discovery", "Pat Example"), ("11:00 AM", "onboarding", "Jamie Client"),
                               ("6:00 PM", "discovery", "Robin Sample")])
        pat = self.res["calls"][0]
        self.assertEqual(sorted(pat["sources"]), ["ghl:discovery_call", "google:primary"])
        self.assertEqual(pat["ghl_contact_id"], "cPat0001")
        self.assertEqual(pat["email"], "pat@example.com")
        self.assertEqual(pat["meet_link"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(pat["page_title"], "Pat Example Call Prep 11/3")
        self.assertEqual(self.res["calls"][2]["meet_link"], "https://meet.google.com/rob-inmt-gxx")

    def test_skips(self):
        names = " ".join(c["title"] for c in self.res["calls"])
        self.assertNotIn("Coach", names)          # 1:1 with an account manager
        self.assertNotIn("Students", names)       # group coaching
        self.assertNotIn("Iterations", names)     # a time block with "Sales" in it
        self.assertNotIn("Drew", names)           # cancelled on both calendars
        self.assertNotIn("Next Day", names)       # another day
        self.assertEqual([n["time_et"] for n in self.res["not_prepped"]], ["3:00 PM"])
        self.assertEqual(self.res["hidden"], [{"calendar": "busy_only", "time_et": "4:00 PM"}])

    def test_already_prepped(self):
        flags = {c["first"]: c["already_prepped"] for c in self.res["calls"]}
        self.assertEqual(flags, {"Pat": False, "Jamie": True, "Robin": False})
        jamie = next(c for c in self.res["calls"] if c["first"] == "Jamie")
        self.assertEqual(jamie["existing_url"], "https://app.notion.com/p/aaa111")

    def test_classify_order(self):
        def k(title, desc="", ext=None):
            e = {"status": "ok", "hidden": False, "source": "google", "title": title, "description": desc,
                 "external": ext or [], "calendar_kind": None}
            return prep.classify_event(e)[0]
        self.assertEqual(k("Discovery Call | Joey x Pat (Lead Suite ad)"), "discovery")
        self.assertEqual(k("(Weekly) post draft"), "internal")
        self.assertEqual(k("Marketing Mastermind"), "coaching")
        self.assertEqual(k("Joey and Casey", "1-1 Call with Account Manager", [{"email": "c@coach.example.org"}]), "coaching")
        self.assertEqual(k("Joey and Robin", "Owner of an assisted living home", [{"email": "robin@example.com"}]), "discovery")

    def test_guess_name(self):
        g = prep.guess_name
        self.assertEqual(g("Discovery Call | Joey x Pat Example"), "Pat Example")
        self.assertEqual(g("Onboarding Call: Joey x Jamie"), "Jamie")
        self.assertEqual(g("Surven & Robin Sample"), "Robin Sample")
        self.assertEqual(g("Morgan Sample discovery"), "Morgan Sample")
        self.assertEqual(g("Joey g and Casey Coach"), "Casey Coach")
        self.assertEqual(g("Joseph Surname and Casey Coach"), "Casey Coach")
        self.assertEqual(g("Joey x Robin"), "Robin")
        self.assertEqual(g("Quick chat", [{"email": "drew.sample@example.com"}]), "Drew Sample")
        self.assertEqual(g("(Please Confirm:) Discovery Call with Surven & Sam Sample"), "Sam Sample")
        self.assertEqual(g("Discovery Call with Pat Example"), "Pat Example")
        self.assertEqual(g("Discovery Call | Jay"), "Jay")

    def test_ghl_calendars(self):
        def k(title, cal):
            e = prep.norm_ghl({"id": "x", "title": title, "startTime": "2026-11-03T15:00:00Z",
                               "appointmentStatus": "confirmed"}, cal)
            return prep.classify_event(e)[0]
        self.assertEqual(k("Lead Suite call | Joey x Pat", "lead_suite_personal"), "discovery")   # never coaching
        self.assertEqual(k("Pat Example", "joseph_personal"), "discovery")
        self.assertEqual(k("Follow up call | Joey x Pat", "client_calls"), "follow-up")
        self.assertEqual(k("Pat Example", "client_calls"), "onboarding")


class GatherTests(FakeGHL):
    def test_gather_reads_ghl_read_only(self):
        cfg = prep.load_config()
        calls = prep.match(json.loads(read("gcal_day.json")), DAY, cfg, ghl_raw(),
                           prep.parse_existing(read("call_prep_page.json")), ["owner@surven.ai"])
        doc = prep.gather(calls, cfg, read("meetings_list.txt"), use_ghl=True)
        self.assertEqual([c["call"]["first"] for c in doc["calls"]], ["Pat", "Robin"])   # Jamie already has a page
        pat = doc["calls"][0]
        self.assertEqual(pat["ghl"]["status"], "ok")
        self.assertEqual(pat["facts"]["total_beds"], 12)
        self.assertEqual(pat["facts"]["community_type"], "Assisted Living")
        self.assertEqual(pat["ghl"]["fields"]["Email Reply Code"], "E99")
        self.assertNotIn("Agent Plan Log", pat["ghl"]["fields"])                        # planner fields stay out
        self.assertEqual(pat["ghl"]["deals"][0]["pipeline"], "Email Pipeline")
        self.assertIn("placement agent", pat["cold_email_reply"]["text"])
        self.assertEqual(pat["signals"], ["burned", "partner", "placement_agents"])
        self.assertIn("Extend the placement agents, never knock them.", pat["reminders"])
        self.assertEqual(len(pat["reminders"]), 3)
        self.assertEqual([p["recording_id"] for p in pat["prior_meetings"]], ["900000009", "900000002"])
        robin = doc["calls"][1]
        self.assertEqual(robin["ghl"]["status"], "not found")
        self.assertEqual(robin["offer"]["tier"], "full_bed_system")

    def test_gather_names_a_call_from_ghl(self):
        cfg = prep.load_config()
        calls = {"day": "2026-11-03", "existing": [], "calls": [
            {"key": "ghl-g9", "kind": "discovery", "title": "Discovery Call", "name": None, "first": None,
             "ghl_contact_id": "cPat0001", "email": None, "day_token": "11/3", "page_title": "Unknown Call Prep 11/3",
             "already_prepped": False}]}
        doc = prep.gather(calls, cfg, None, use_ghl=True)
        c = doc["calls"][0]["call"]
        self.assertEqual((c["name"], c["first"], c["page_title"]), ("Pat Example", "Pat", "Pat Example Call Prep 11/3"))
        self.assertEqual(c["email"], "pat@example.com")
        calls["existing"] = [{"title": "Pat Example Call Prep 11/3", "url": "https://app.notion.com/p/x"}]
        calls["calls"][0].update(name=None, first=None, email=None)
        doc = prep.gather(calls, cfg, None, use_ghl=True)
        self.assertEqual((doc["calls"], [s["first"] for s in doc["skipped"]]), ([], ["Pat"]))


class PrescribeTests(unittest.TestCase):
    def tier(self, **facts):
        return prep.prescribe(facts)["tier"]

    def test_rules(self):
        self.assertEqual(self.tier(community_type="Skilled Nursing Facility"), "route_out")
        self.assertEqual(self.tier(community_type="Sober living / recovery"), "route_out")
        self.assertEqual(self.tier(operating=False), "route_out")
        self.assertEqual(self.tier(below_break_even=True), "route_out")
        self.assertEqual(self.tier(travel_nurse=True), "travel_nurse")
        self.assertEqual(self.tier(can_fund_ads=False), "referral_starter")
        self.assertEqual(self.tier(empty_beds=10, staffing_ok=True), "full_bed_system_resident_headline")
        self.assertEqual(self.tier(empty_beds=10), "full_bed_system")
        self.assertEqual(self.tier(), "full_bed_system")

    def test_why_and_verify(self):
        rx = prep.prescribe({"empty_beds": 10, "uses_placement_agents": True})
        self.assertTrue(any("capacity screen" in w for w in rx["why"]))
        self.assertTrue(any("placement" in w for w in rx["why"]))
        self.assertIn("If 5 more families toured next month, could you staff them?", rx["verify"])
        self.assertIn("tours", rx["guarantee"])
        self.assertTrue(rx["downsells"])
        self.assertEqual(prep.prescribe({"can_fund_ads": False})["downsells"], [])


class RenderTests(unittest.TestCase):
    def item(self, **page):
        base = {"qualifying": ["How many empty today?"], "suspect_pains": ["Agents slow"], "timeline": ["How long?"],
                "wants": ["Both rooms full"], "other_notes": [], "callout": ["Ask, then stop."], "sources": []}
        base.update(page)
        return {"call": {"key": "ghl-g1", "kind": "discovery", "first": "Pat", "name": "Pat Example",
                         "time_et": "10:00 AM", "meet_link": "https://meet.google.com/abc-defg-hij",
                         "page_title": "Pat Example Call Prep 11/3", "sources": ["ghl:discovery_call"]},
                "facts": {"empty_beds": 2}, "web_facts": [{"fact": "12 beds", "url": "https://example.gov/x"}],
                "expect": ["Let me think about it. Validate."], "reminders": ["W"], "page": base}

    def test_fixed_order(self):
        tmp = tempfile.mkdtemp()
        try:
            doc, bad = prep.render({"day": "2026-11-03", "calls": [self.item()]}, tmp)
            self.assertEqual(bad, 0)
            md = read_abs(doc["pages"][0]["md"])
            order = ["MEET LINK:", "QUALIFYING", "SUSPECT PAINS", "TIMELINE", "WANTS", "OTHER NOTES",
                     '<callout icon="\U0001F534" color="red_bg">', "DO DIFFERENT FOR PAT", "<toggle>"]
            pos = [md.index(x) for x in order]
            self.assertEqual(pos, sorted(pos))
            self.assertTrue(md.startswith("<b>MEET LINK:</b> [https://meet.google.com/abc-defg-hij]"))
            self.assertIn("- Tier: 90 Day Full Bed System", md)
            self.assertIn("Fact: 12 beds ([source](https://example.gov/x))", md)
            self.assertIn("Expect: Let me think about it.", md)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dashes_removed_and_limits(self):
        tmp = tempfile.mkdtemp()
        try:
            it = self.item(suspect_pains=["Agents slow \u2014 always", "b", "c", "d"],
                           wants=["one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                  "fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree "
                                  "twentyfour twentyfive twentysix"])
            it["web_facts"] = [{"fact": "No link fact"}]
            doc, bad = prep.render({"calls": [it]}, tmp)
            p = doc["pages"][0]
            self.assertEqual(bad, 1)
            joined = " ".join(p["issues"])
            self.assertIn("suspect_pains has 4 bullets", joined)
            self.assertIn("wants bullet is 26 words", joined)
            self.assertIn("no link and is not marked inferred", joined)
            md = read_abs(p["md"])
            self.assertNotIn("\u2014", md)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_meet_link(self):
        it = self.item()
        it["call"]["meet_link"] = None
        md = prep.render_md(it, prep.compose(it, prep.load_offer_rules()), "now")
        self.assertIn("not on the invite. Check the booking email.", md)

    def test_finish(self):
        pages = {"pages": [{"key": "a", "time_et": "10:00 AM", "first": "Pat", "kind": "discovery"},
                           {"key": "b", "time_et": "6:00 PM", "first": "Robin", "kind": "discovery"}]}
        line, sms = prep.finish(pages, {"a": "u"}, hidden=[{"time_et": "4:00 PM"}],
                                skipped=[{"time_et": "11:00 AM", "first": "Jamie"}])
        self.assertIn("2 call(s), 1 page(s) written", line)
        self.assertIn("Not written: 6:00 PM Robin", line)
        self.assertIn("Already had a prep page: 11:00 AM Jamie", line)
        self.assertIn("4:00 PM", line)
        self.assertEqual(sms, "Call prep ready in Notion (Call Prep): 10:00 AM Pat (Discovery).")
        self.assertIsNone(prep.finish(pages, {}, dry_run=True)[1])
        self.assertEqual(prep.finish({"pages": []}, {})[0], "Call Prep: no new sales calls to prep today.")


if __name__ == "__main__":
    unittest.main()
