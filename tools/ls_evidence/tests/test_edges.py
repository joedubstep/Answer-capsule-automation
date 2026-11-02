"""Edge cases: names that are really phone fragments, call lengths for leads with no booking, one person on two GHL
records, contacts left out in settings, and the wording rules for every text file of this tool."""
import glob
import os
import re
import unittest

from tools.ls_evidence import profile as prof
from tools.ls_evidence import render
from tools.ls_evidence import score as S
from tools.ls_evidence.tests import fixtures as fx
from tools.ls_evidence.tests.base import FakeGHL

REPO = prof.REPO


class PhoneFragmentNameTest(FakeGHL):
    """A contact whose first name field holds an area code, like "(555)", shows as "No name", never the digits."""

    def patch(fs):
        for c in fs["contacts__search.json"]["contacts"]:
            if c["id"] == "cPat00001":
                c.update(firstName="(555)", lastName="010-0001", contactName="(555) 010-0001")

    def test_no_digits_in_names(self):
        raw = self.raw()
        self.assertEqual(raw["leads"]["cPat00001"]["first"], "")
        h = render.render(self.evidence(raw=raw))
        self.assertNotIn("(555)", h)
        self.assertIn("No name (41)", h)


class CallLengthForEveryLeadTest(FakeGHL):
    """Lee never booked, but his answered auto-dialer call has no length in GHL, so the pull reads its transcript."""

    def patch(fs):
        box = fs["conversations__vLee__messages.json"]["messages"]["messages"]
        box.insert(0, fx.msg("l7", "cLee00003", "2026-11-01T13:00:30.000Z", fx.OUT, fx.CC, "completed", "workflow"))
        fs[f"conversations__locations__{fx.LOC}__messages__l7__transcription.json"] = [
            {"sentenceIndex": 0, "transcript": "hello this is a voicemail box", "speaker": 1}]

    def test_length_read_and_short_pickup_is_not_a_talk(self):
        raw = self.raw()
        self.assertEqual(raw["call_details"]["l7"], {"duration": None, "words": 6})
        self.assertNotIn("cLee00003", raw["notes"])                 # notes stay booked-only
        lee = next(r for r in self.evidence(raw=raw)["leads"] if r["first"] == "Lee")
        # 6 words is about 3 seconds: a voicemail pickup, so it is just a fourth dial, not a talk
        self.assertEqual(lee["boxes"]["lead_replied"]["a"], S.NO)
        self.assertEqual(lee["boxes"]["triple_dial"]["a"], S.YES)
        self.assertIsNone(lee["boxes"]["triple_dial"]["check"])


class OnePersonTwoRecordsTest(FakeGHL):
    """Kim is Pat filling the form twice (same phone). A call booked on either record counts, once."""

    def patch(fs):
        evs = fs["calendars__events.json"]["events"]
        for eid, cid in (("eKim", "cKim00008"), ("ePatTwin", "cPat00001")):
            evs.append({"id": eid, "calendarId": fx.DISC, "contactId": cid, "startTime": "2026-10-23T11:00:00-04:00",
                        "endTime": "2026-10-23T11:30:00-04:00", "dateAdded": "2026-10-21T15:00:00.000Z",
                        "appointmentStatus": "showed", "deleted": False, "title": "Discovery Call",
                        "createdBy": {"source": "booking_widget"}})

    def test_counts_once(self):
        ev = self.evidence()
        rows = [c for c in ev["calls"] if c["start_et"] == "Fri Oct 23, 11am"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(1 for c in rows if c["counts"]), 1)
        self.assertIn("same call as on this lead's other GHL record", [c["count_why"] for c in rows])
        self.assertEqual(ev["scoreboard"]["qualified_booked"], 4)          # 3 from the base fixtures, plus this one


class ExcludeInSettingsTest(FakeGHL):
    def test_contact_ids_left_out(self):
        self.settings["exclude"]["contact_ids"] = ["cPat00001"]
        ev = self.evidence()
        self.assertNotIn("Pat", {r["first"] for r in ev["leads"]})
        self.assertEqual(ev["excluded"]["test"], 2)
        self.assertEqual(S.is_excluded({"id": "x", "tags": []}, None, ["x"]), "left out in settings")


class StaffContactTest(FakeGHL):
    """A GHL user's own test contact (same phone, or same full name) is never scored as a lead. Only one-way keys are
    kept, never the user's phone, email or name."""

    def patch(fs):
        fs["users.json"]["users"] += [
            {"id": "u2", "firstName": "Someone", "lastName": "Else", "email": "", "phone": "+1 555 010 0009"},
            {"id": "u3", "firstName": "Robin", "lastName": "Example", "email": "", "phone": ""},
            {"id": "u4", "firstName": "Gone", "lastName": "User", "phone": "+15550100001", "deleted": True}]

    def test_left_out(self):
        raw = self.raw()
        blob = str(raw["staff"])
        for plain in ("555", "Robin", "staff@example.com", "Someone"):
            self.assertNotIn(plain, blob)
        ev = self.evidence(raw=raw)
        names = {r["first"] for r in ev["leads"]}
        self.assertNotIn("Jordan", names)          # same phone as a user
        self.assertNotIn("Robin", names)           # same full name as a user
        self.assertIn("Pat", names)                # a deleted user does not count
        self.assertEqual(ev["excluded"]["test"], 3)


class UsersUnreadableTest(FakeGHL):
    drop = ("users.json",)

    def test_error_recorded_and_run_goes_on(self):
        raw = self.raw()
        self.assertEqual([e[0] for e in raw["errors"]], ["users"])
        self.assertEqual(raw["staff"], [])
        self.assertIn("Pat", {r["first"] for r in self.evidence(raw=raw)["leads"]})


class FooterTest(FakeGHL):
    def test_rules_in_plain_clock_times(self):
        h = render.render(self.evidence())
        self.assertIn("A lead who comes in after 9pm or before 8am on their own clock is due from 8am.", h)
        self.assertIn("Quiet hours are 8:45pm to 8am", h)
        self.assertIn("from 5am until 12pm or the call", h)
        self.assertNotIn("20:45", h)


class WordingTest(unittest.TestCase):
    """Every text file of this tool: no em or en dashes, no banned refund-case word, no personal names, US spelling
    in what Joey reads."""

    def files(self):
        out = glob.glob(os.path.join(REPO, "tools", "ls_evidence", "**", "*.*"), recursive=True)
        out += [os.path.join(REPO, ".claude", "skills", "ls_evidence", "SKILL.md"),
                os.path.join(REPO, "routines", "ls_evidence.md")]
        return [p for p in out if p.endswith((".py", ".md", ".json")) and "__pycache__" not in p]

    def test_rules(self):
        from tools.ls_evidence import pull
        self.assertEqual(pull.TEST_NAMES, {"test", "test test", "test test test"})   # people to skip go by id
        banned = ("charge" + "back",)
        for p in self.files():
            with open(p, encoding="utf-8") as f:
                text = f.read()
            low = text.lower()
            self.assertNotRegex(text, "[" + chr(0x2013) + chr(0x2014) + "]", p)
            for w in banned:
                self.assertNotIn(w, low, p)
            if p.endswith((".md", "settings.json")):
                prose = re.sub(r'"cancelled"', "", low)       # a GHL status value, not a word Joey reads
                self.assertNotRegex(prose, r"\bcancelled\b|\bcolour|\bbehaviour|\borganis", p)


if __name__ == "__main__":
    unittest.main()
