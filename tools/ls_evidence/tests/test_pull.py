import json
import unittest

from tools.ls_evidence import profile as prof
from tools.ls_evidence import pull
from tools.ls_evidence.tests import fixtures as fx
from tools.ls_evidence.tests.base import FakeGHL


class PullTest(FakeGHL):
    def test_reads_every_part(self):
        raw = self.raw()
        self.assertEqual(raw["errors"], [])
        self.assertNotIn("fatal", raw)
        # tagged contacts plus the pipeline-only one (Taylor), never the untagged referral
        self.assertIn("cTay00011", raw["leads"])
        self.assertNotIn("cNoise012", raw["leads"])
        self.assertEqual(len(raw["leads"]), 11)
        # messages only for leads since ads went live (not Morgan, who came in before)
        self.assertNotIn("cMor00010", raw["messages"])
        self.assertIn("cJor00009", raw["messages"])
        self.assertEqual(raw["stages"][fx.ST["no_show"]], "No Show")

    def test_fields_found_by_key_and_name(self):
        raw = self.raw()
        self.assertEqual(raw["field_ids"]["sms1"], "fakeSms1Field000001")
        self.assertEqual(raw["field_how"]["sms1"], "key")
        self.assertEqual(raw["field_ids"]["triple_dial"], "Joxd7amkJniU3raFVIcr")
        self.assertEqual(raw["leads"]["cAlex0004"]["fields"]["sms1"], ["No"])
        self.assertEqual(raw["leads"]["cRob00005"]["fields"]["reply_code"], 55)

    def test_no_phone_email_or_message_text_kept(self):
        raw = self.raw()
        blob = json.dumps({"l": raw["leads"], "m": raw["messages"], "e": raw["events"]})
        self.assertNotIn("@example.com", blob)
        self.assertNotIn("555010", blob)
        self.assertNotIn("+1555", blob)
        self.assertNotIn("555-201-4477", blob)           # the number Sam texted
        self.assertNotIn("Joey x", blob)                 # event titles are not kept
        self.assertNotIn("who is this", blob)

    def test_duplicate_keys_match_across_formats(self):
        raw = self.raw()
        self.assertEqual(raw["leads"]["cPat00001"]["dup"][0], raw["leads"]["cKim00008"]["dup"][0])

    def test_email_direction_from_meta(self):
        raw = self.raw()
        em = next(m for m in raw["messages"]["cSam00002"]["msgs"] if m["type"] == "TYPE_EMAIL")
        self.assertEqual(em["dir"], "outbound")
        self.assertIn("REQUIRED-URGENT", em["subject"])

    def test_call_length_and_notes_only_for_booked_leads(self):
        raw = self.raw()
        self.assertEqual(raw["call_details"], {"t1": {"duration": None, "words": 200}})
        self.assertEqual(set(raw["notes"]), {"cSam00002", "cRob00005", "cCas00006", "cTay00011"})

    def test_events_kept_slim_with_kinds(self):
        raw = self.raw()
        kinds = {e["id"]: (e["cal"], e["title_kind"], e["status"]) for e in raw["events"]}
        self.assertEqual(kinds["eOnb"], ("discovery", "client", "confirmed"))
        self.assertEqual(kinds["eSamCopy"], ("lead_suite", "discovery", "confirmed"))
        self.assertEqual(kinds["eOther"], ("lead_suite", "other", "confirmed"))
        self.assertEqual(kinds["eTay"][2], "noshow")

    def test_bound_on_leads(self):
        raw = self.raw(max_leads=3)
        self.assertEqual(len(raw["messages"]), 3)
        self.assertEqual(raw["errors"][0][0], "bound")


class NoAccessTest(FakeGHL):
    drop = ("contacts.json",)

    def test_fatal_without_access(self):
        raw = self.raw()
        self.assertIn("no access", raw["fatal"])
        self.assertEqual(raw["leads"], {})


class BrokenPartsTest(FakeGHL):
    drop = ("conversations__vLee__messages.json", "calendars__events.json",
            f"locations__{fx.LOC}__customFields.json")

    def test_errors_recorded_not_raised(self):
        raw = self.raw()
        kinds = sorted({e[0] for e in raw["errors"]})
        self.assertEqual(kinds, ["customFields", "events", "messages"])
        self.assertFalse(raw["messages"]["cLee00003"]["ok"])
        # field ids fall back to the probe ids; the made-up SMS ids are then unknown
        self.assertEqual(raw["field_how"]["triple_dial"], "fallback id")
        self.assertNotIn("sms1", raw["field_ids"])

    def test_unreadable_messages_make_unknown_boxes(self):
        ev = self.evidence()
        lee = next(r for r in ev["leads"] if r["first"] == "Lee")
        self.assertEqual(lee["boxes"]["triple_dial"]["a"], "Unknown")
        self.assertEqual(lee["boxes"]["lead_replied"]["a"], "Unknown")


class TagFilterRefusedTest(FakeGHL):
    """If the tag filter is refused, the pull scans all contacts and keeps the tagged ones."""

    def test_full_scan_fallback(self):
        from shared import ghl
        real = ghl.search_contacts
        calls = []

        def fake(loc, filters=None, **kw):
            calls.append(filters)
            if filters:
                return {"error": 422, "body": "bad filter"}
            return real(loc, **kw)
        ghl.search_contacts = fake
        try:
            raw = self.raw()
        finally:
            ghl.search_contacts = real
        self.assertEqual(len(calls), 2)
        self.assertIn("cPat00001", raw["leads"])
        self.assertEqual(raw["errors"][0][0], "contacts search (tag filter)")


class ProfileTest(unittest.TestCase):
    def test_hq_and_agc_from_config(self):
        hq = prof.resolve("hq")
        self.assertEqual(hq["location"], fx.LOC)
        self.assertEqual(hq["pipeline"], fx.LS)
        self.assertEqual(hq["calendars"], {"discovery": fx.DISC, "lead_suite": fx.LSCAL})
        agc = prof.resolve("agc")
        self.assertIsNone(agc["pipeline"])
        self.assertIn("discovery", agc["calendars"])

    def test_fields_by_name_when_ids_and_keys_differ(self):
        ids, how = prof.resolve_fields([{"id": "a1", "name": "STL SMS1 Sent", "fieldKey": "contact.other"},
                                        {"id": "a2", "name": "STL SMS 2 Done"}, {"id": "a3", "name": "STL SMS3"},
                                        {"id": "a4", "name": "STL Outcome"}, {"id": "a5", "name": "STL Outcome Reason"},
                                        {"id": "a6", "name": "Agent Meeting Brief"}])
        self.assertEqual({k: ids[k] for k in ("sms1", "sms2", "sms3", "outcome", "outcome_reason", "meeting_brief")},
                         {"sms1": "a1", "sms2": "a2", "sms3": "a3", "outcome": "a4", "outcome_reason": "a5",
                          "meeting_brief": "a6"})
        self.assertEqual(how["sms1"], "name")
        self.assertNotIn("triple_dial", ids)

    def test_unreadable_list_uses_probe_ids(self):
        ids, how = prof.resolve_fields(None)
        self.assertEqual(ids["lead_in_at"], "ntJnTEIUoaeilJ8CSGM2")
        self.assertEqual(ids["reply_code"], "5qNYXRzPs55rPUtRwoxD")


if __name__ == "__main__":
    unittest.main()
