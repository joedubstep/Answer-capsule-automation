"""Monday: the partner call list and the open rooms email."""
from tools.client_desk import partners as P
from tools.client_desk import email_draft as EM
from tools.client_desk.tests.base import FakeGHL


class CallList(FakeGHL):
    def call(self):
        raw, _, cls = self.built("monday")
        return raw, P.call_list(raw, cls, self.now)

    def test_groups(self):
        _, call = self.call()
        self.assertEqual(call["counts"], {"first_calls": 2, "check_ins": 1, "weekly_note": 3, "thank_yous": 1})
        g = {x["key"]: x for x in call["groups"]}
        self.assertEqual([r["code"] for r in g["first_calls"]["rows"]], ["P2", "P1"])   # never touched goes first
        self.assertEqual(g["check_ins"]["rows"][0]["code"], "P3")
        self.assertEqual(g["thank_yous"]["rows"][0]["code"], "P6")
        self.assertEqual(sorted(r["code"] for r in g["weekly_note"]["rows"]), ["P4", "P5", "P6"])

    def test_rows_are_safe(self):
        _, call = self.call()
        for g in call["groups"]:
            self.assertTrue(g["ask"])                                   # bullets of what to ask, never a script
            for r in g["rows"]:
                self.assertNotRegex(repr(r), r"\d{7,}|@")
        p1 = next(r for g in call["groups"] for r in g["rows"] if r["code"] == "P1")
        self.assertEqual(p1["place"], "Northside Hospital")
        self.assertEqual(p1["type"], "hospital")
        self.assertEqual(p1["note"], "A large hospital desk.")
        self.assertEqual(p1["tries"], 1)
        self.assertIn("no answer", p1["last_how"])

    def test_recipients(self):
        _, call = self.call()
        rc = P.recipients(call)
        self.assertEqual(rc["count"], 2)
        self.assertEqual(rc["no_email"], ["Central Agency P5"])
        self.assertEqual(rc["not_tagged"], [])

    def test_no_partner_pipeline(self):
        raw, _, cls = self.built("monday")
        raw["partner_pipeline_id"] = None
        self.assertIsNone(P.call_list(raw, cls, self.now))
        self.assertIsNone(P.recipients(None))


class Email(FakeGHL):
    def draft(self):
        raw, _, cls = self.built("monday")
        return raw, EM.build(raw, self.profile(), P.recipients(P.call_list(raw, cls, self.now)))

    def test_structure(self):
        _, d = self.draft()
        self.assertEqual(d["subject"], "Private and shared rooms this week")
        body = d["body"]
        self.assertTrue(body.startswith("Hi {{contact.first_name}},"))
        self.assertIn("[N] private and [N] shared rooms open", body)
        self.assertIn("at Sample Grove Home in Springfield", body)
        self.assertIn("{{location.phone}}", body)
        self.assertIn("samplegrove.example.com", body)
        self.assertEqual(d["blanks"], 2)
        self.assertNotRegex(body, r"\d{3}[\s.-]?\d{4}")                # no phone number typed into the draft
        self.assertNotRegex(body, "[\u2012-\u2015]")

    def test_copy_checked_as_client(self):
        _, d = self.draft()
        self.assertTrue(d["check"]["body"]["ok"], d["check"]["body"])
        self.assertTrue(d["check"]["subject"]["ok"])
        self.assertTrue(d["check"]["owner_text"]["ok"])
        self.assertEqual(EM.held(d), [])

    def test_last_sent(self):
        _, d = self.draft()
        self.assertEqual(d["last_sent"]["recipients"], 2)
        self.assertEqual(set(d["last_sent"]["subjects"]), {"Private and shared rooms this week", "Discharges this week?"})

    def test_skip(self):
        raw, d = self.draft()
        p = dict(self.profile(), open_beds_email=None)
        self.assertIn("skip", EM.build(raw, p, None))
        raw["partner_pipeline_id"] = None
        self.assertIn("skip", EM.build(raw, self.profile(), None))

    def test_held_when_a_rule_breaks(self):
        raw, _ = self.draft()
        p = self.profile()
        p = dict(p, open_beds_email=dict(p["open_beds_email"], services_line="We care for patients at our care home."))
        d = EM.build(raw, p, None)
        self.assertEqual(EM.held(d), ["body"])
        rules = {b["rule"] for b in d["check"]["body"]["blocks"]}
        self.assertTrue({"patients", "care_home"} <= rules, rules)
