import json
import unittest

from tools.hq_desk import pull, profile
from tools.hq_desk.tests import fixtures as fx
from tools.hq_desk.tests.base import FakeGHL


class PullTest(FakeGHL):
    def test_reads_every_part(self):
        raw = self.raw()
        self.assertEqual(raw["errors"], [])
        self.assertNotIn("fatal", raw)
        self.assertEqual(len(raw["opportunities"]), 10)
        # every open deal's contact, never the lost one
        self.assertEqual(len(raw["contacts"]), 9)
        self.assertNotIn("cLost0010", raw["contacts"])
        # pipeline keys and stage names come along
        self.assertEqual({p["key"] for p in raw["pipelines"]}, {"email", "leadsuite", "warm_referral", "normal_lead"})
        self.assertIn("Follow Up", [s["name"] for p in raw["pipelines"] for s in p["stages"]])

    def test_deals_filtered_to_their_pipeline(self):
        # the fake answers every pipeline with the same list; each deal must still appear once, in its own pipeline
        raw = self.raw()
        ids = [o["id"] for o in raw["opportunities"]]
        self.assertEqual(len(ids), len(set(ids)))
        o4 = next(o for o in raw["opportunities"] if o["id"] == "o4")
        self.assertEqual(o4["pipeline"], "email")

    def test_no_phone_or_email_kept(self):
        raw = self.raw()
        blob = json.dumps({"c": raw["contacts"], "o": raw["opportunities"]})
        self.assertNotIn("@example.com", blob)
        self.assertNotIn("+1555", blob)

    def test_fields_by_role(self):
        raw = self.raw()
        c = raw["contacts"]["cReply004"]
        self.assertEqual(c["fields"]["email_code"], "24")
        self.assertEqual(raw["contacts"]["cHot0001"]["fields"]["reply_code"], "41")

    def test_messages_slim_and_clean(self):
        raw = self.raw()
        m = raw["conversations"]["cReply004"]["messages"][0]
        self.assertEqual(m["dir"], "inbound")              # direction from meta.email
        self.assertEqual(m["text"], "Yes, we have 3 open beds. What does it cost?")   # quote and HTML gone
        hot = raw["conversations"]["cHot0001"]["messages"]
        self.assertEqual([x["id"] for x in hot], ["h4", "h3", "h2", "h1"])   # newest first

    def test_meetings_only_from_the_meeting_calendar(self):
        raw = self.raw()
        self.assertEqual({e["id"] for e in raw["events"]}, {"e1", "e2", "e3", "e4"})

    def test_bound_on_contacts(self):
        raw = pull.pull(fx.profile(), now=fx.NOW, max_deals=3, workers=1)
        self.assertEqual(len(raw["contacts"]), 3)
        self.assertEqual(raw["errors"][0][0], "bound")


class NoAccessTest(FakeGHL):
    drop = ("contacts.json",)

    def test_fatal_without_access(self):
        raw = self.raw()
        self.assertIn("no access", raw["fatal"])
        self.assertEqual(raw["contacts"], {})


class BrokenPartsTest(FakeGHL):
    drop = ("conversations__vHot__messages.json", "calendars__events.json")

    def test_errors_recorded_not_raised(self):
        raw = self.raw()
        kinds = sorted(e[0] for e in raw["errors"])
        self.assertEqual(kinds, ["events", "messages"])
        self.assertIn("cHot0001", raw["contacts"])


class CleanBodyTest(unittest.TestCase):
    def test_html_and_quotes(self):
        self.assertEqual(pull.clean_body("<div>Hi&nbsp;there</div><br>&gt; old"), "Hi there")
        self.assertEqual(pull.clean_body("Sounds good\nSent from my iPhone"), "Sounds good")
        self.assertTrue(pull.clean_body("x " * 500).endswith("..."))


class SlimMessagesTest(unittest.TestCase):
    def test_joeys_text_survives_a_run_of_workflow_texts(self):
        def m(i, d, src, body):
            return {"id": str(i), "dateAdded": f"2026-11-0{i}T12:00:00.000Z", "direction": d,
                    "messageType": "TYPE_SMS", "source": src, "body": body}
        out = pull.slim_messages([m(5, "outbound", "workflow", "auto one"), m(4, "outbound", "workflow", "auto two"),
                                  m(3, "outbound", "workflow", "auto three"), m(2, "outbound", "app", "Joey wrote this"),
                                  m(1, "inbound", None, "Lead wrote this")])
        texts = {x["id"]: x.get("text") for x in out}
        self.assertEqual(texts["2"], "Joey wrote this")
        self.assertEqual(texts["1"], "Lead wrote this")
        self.assertEqual(texts["5"], "auto one")
        self.assertIsNone(texts["4"])


class ProfileTest(unittest.TestCase):
    def test_hq_and_agc_from_config(self):
        hq = profile.resolve("hq")
        self.assertEqual(hq["location"], fx.LOC)
        self.assertEqual(hq["meeting_calendar"], fx.CAL)
        self.assertEqual([p["key"] for p in hq["pipelines"]][:3], ["email", "leadsuite", "warm_referral"])
        agc = profile.resolve("agc")
        self.assertEqual(agc["location"], "ySKGXQBLqevOlFCmV1Wo")
        self.assertTrue(agc["meeting_calendar"])

    def test_fields_by_name_when_ids_differ(self):
        got = profile.resolve_fields([{"id": "a1", "name": "Agent Promises Owed"}, {"id": "a2", "name": "Agent Stage"},
                                      {"id": "a3", "name": "Partner Code"}, {"id": "a4", "name": "Agent Plan Log"}])
        self.assertEqual(got, {"owed": "a1", "stage": "a2", "partner_code": "a3", "log": "a4"})


if __name__ == "__main__":
    unittest.main()
