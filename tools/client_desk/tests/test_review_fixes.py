"""Regression tests for the review fixes: calls that never rang, the bulk open rooms email, which callers get a
transcript read, and conversation dates that come back as text. Synthetic data only (555 numbers, example.com)."""
import os

from tools.client_desk import metrics as M
from tools.client_desk import partners as P
from tools.client_desk import pull
from tools.client_desk.tests.base import FakeGHL
from tools.client_desk.tests import fixtures as fx


def with_extra(build_extra):
    """A FakeGHL subclass mixin: rewrite the fake dir with extra synthetic data before each test."""
    class Extra(FakeGHL):
        def setUp(self):
            super().setUp()
            d = fx.build()
            build_extra(d)
            fx.write_fake_dir(self.fake, data=d)
    return Extra


def _cancelled_calls(d):
    # a family and a partner each get a workflow call this week that GoHighLevel cancelled before it rang
    d["messages"].append(fx.msg("fam4", "TYPE_CAMPAIGN_CALL", "outbound", fx.at(hours=29), status="canceled",
                                cst="failed", source="workflow"))
    d["messages"].append(fx.msg("p2", "TYPE_CAMPAIGN_CALL", "outbound", fx.at(days=1), status="canceled",
                                cst="failed", source="workflow"))


class CallsThatNeverRang(with_extra(_cancelled_calls)):
    def test_not_counted_as_calls_made(self):
        _, desk, _ = self.built()
        self.assertEqual(desk["activity"]["calls"], 2)               # same as without the cancelled calls

    def test_not_a_first_contact_or_an_answer(self):
        _, desk, _ = self.built()
        waiting = {r["cid"] for r in desk["unanswered"]}
        self.assertIn("fam4", waiting)                               # the cancelled call did not answer her text
        self.assertEqual(desk["families"]["speed_week_n"], 1)

    def test_not_a_partner_touch(self):
        raw, desk, cls = self.built()
        self.assertEqual(desk["partners"]["touches"]["partners_touched"], 2)
        call = P.call_list(raw, cls, self.now)
        p2 = next(r for g in call["groups"] for r in g["rows"] if r["code"] == "P2")
        self.assertEqual(p2["tries"], 0)
        self.assertIsNone(p2["last_touch"])

    def test_placed(self):
        self.assertFalse(M.placed({"type": "TYPE_CAMPAIGN_CALL", "dir": "outbound", "cst": "failed"}))
        self.assertTrue(M.placed({"type": "TYPE_CAMPAIGN_CALL", "dir": "outbound", "cst": "no-answer"}))
        self.assertFalse(M.placed({"type": "TYPE_CALL", "dir": "inbound", "cst": "completed"}))


def _bulk_only(d):
    # Westside Nursing (Talked, last call 20 days ago) gets this week's bulk open rooms email: still due a check-in.
    # Harbor Social Work (Sent a Referral 4 days ago) gets only the bulk email after the referral: still due a thank-you.
    d["messages"].append(fx.msg("p3", "TYPE_EMAIL", "outbound", fx.at(days=2), status="sent", source="app",
                                subject="Private and shared rooms this week", body="<p>Hi</p>"))
    d["messages"].append(fx.msg("p6", "TYPE_EMAIL", "outbound", fx.at(days=2), status="sent", source="app",
                                subject="This week's open rooms in Springfield", body="<p>Hi</p>"))


class BulkEmailIsNotATouch(with_extra(_bulk_only)):
    def call(self):
        raw, _, cls = self.built("monday")
        return {r["code"]: (g["key"], r) for g in P.call_list(raw, cls, self.now)["groups"] for r in g["rows"]
                if g["key"] in ("check_ins", "thank_yous")}

    def test_check_in_still_due(self):
        rows = self.call()
        self.assertEqual(rows["P3"][0], "check_ins")
        self.assertEqual(rows["P3"][1]["days"], 20)
        self.assertEqual(rows["P3"][1]["last_open_rooms_days"], 2)

    def test_thank_you_still_due(self):
        self.assertEqual(self.call()["P6"][0], "thank_yous")

    def test_bulk_send_does_not_answer_a_reply(self):
        _, desk, _ = self.built()
        self.assertIn("p6", {r["cid"] for r in desk["unanswered"]})

    def test_open_beds_send(self):
        self.assertTrue(M.open_beds_send({"type": "TYPE_EMAIL", "dir": "outbound", "subj": "Private and shared rooms this week"}))
        self.assertTrue(M.open_beds_send({"type": "TYPE_EMAIL", "dir": "outbound", "subj": "This week's open rooms in X"}))
        self.assertFalse(M.open_beds_send({"type": "TYPE_EMAIL", "dir": "inbound", "subj": "Re: Private and shared rooms this week"}))
        self.assertFalse(M.open_beds_send({"type": "TYPE_EMAIL", "dir": "outbound", "subj": "Thank you"}))


def _partner_and_vendor_calls(d):
    # a partner and an already judged vendor call in with recordings: their transcripts are never read
    d["messages"].append(fx.msg("p1", "TYPE_CALL", "inbound", fx.at(days=1), status="completed", dur=90,
                                cst="completed", rec=True, mid="m_p1_in"))
    d["transcripts"]["m_p1_in"] = [{"mediaChannel": 1, "transcript": "Hello, this is the case manager."}]
    d["messages"].append(fx.msg("job1", "TYPE_CALL", "inbound", fx.at(days=1), status="completed", dur=40,
                                cst="completed", rec=True, mid="m_job_in"))
    d["transcripts"]["m_job_in"] = [{"mediaChannel": 1, "transcript": "Are you hiring?"}]


class TranscriptsOnlyForUnknownCallers(with_extra(_partner_and_vendor_calls)):
    def test_scope(self):
        raw = self.raw()
        self.assertNotIn("m_p1_in", raw["transcripts"])
        self.assertNotIn("m_job_in", raw["transcripts"])
        unknown_calls = {m["id"] for m in raw["messages"] if m["cid"] in ("u1", "u2n", "u3", "u4", "u5")}
        self.assertTrue(unknown_calls <= set(raw["transcripts"]))

    def test_maybe_unknown_caller(self):
        self.assertTrue(pull.maybe_unknown_caller({"named": False, "tags": [], "fields": {}}))
        self.assertTrue(pull.maybe_unknown_caller({"named": False, "tags": [], "fields": {"agent_stage": "new"}}))
        self.assertFalse(pull.maybe_unknown_caller({"named": True, "tags": [], "fields": {}}))
        self.assertFalse(pull.maybe_unknown_caller({"named": False, "tags": ["partner-hospital"], "fields": {}}))
        self.assertFalse(pull.maybe_unknown_caller({"named": False, "tags": [],
                                                    "fields": {"agent_stage": "not a family: vendor"}}))


class TextDates(FakeGHL):
    def test_conversation_dates_as_text(self):
        # lastMessageDate sometimes arrives as an ISO string: the read still works and still stops at the window
        import json
        path = os.path.join(self.fake, "conversations__search.json")
        with open(path) as f:
            box = json.load(f)
        for row in box["conversations"]:
            row["lastMessageDate"] = M.et.parse(row["lastMessageDate"]).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            row.pop("sort", None)
        with open(path, "w") as f:
            json.dump(box, f)
        raw = self.raw()
        self.assertEqual(raw["message_source"], "conversations")
        self.assertEqual(len(raw["messages"]), len(fx.build()["messages"]) - 30)


def _closers(d):
    # after our one-to-one email, Central Agency only says thanks (no answer needed); Eastside Rehab asks a question
    d["messages"].append(fx.msg("p5", "TYPE_EMAIL", "outbound", fx.at(days=4), status="sent", source="app",
                                subject="Info for your desk", body="<p>Hi</p>"))
    d["messages"].append(fx.msg("p5", "TYPE_EMAIL", "inbound", fx.at(days=3), subject="Re: Info for your desk",
                                body="Thanks received. Pat Example, Central Agency"))
    d["messages"].append(fx.msg("p2", "TYPE_EMAIL", "inbound", fx.at(days=3), subject="Rooms",
                                body="Thanks for calling. Do you take residents on Medicaid?"))


class PoliteClosers(with_extra(_closers)):
    def test_closer_is_not_waiting_but_a_question_is(self):
        _, desk, _ = self.built()
        waiting = {r["cid"] for r in desk["unanswered"]}
        self.assertNotIn("p5", waiting)
        self.assertIn("p2", waiting)
