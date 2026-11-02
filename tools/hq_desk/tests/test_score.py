import datetime as dt
import unittest

from tools.hq_desk import score
from tools.hq_desk.tests import fixtures as fx
from tools.hq_desk.tests.base import FakeGHL

NOW = fx.NOW


def m(when_h, direction, mtype="TYPE_SMS", source="app", status="delivered", text=None):
    d = {"id": f"{direction}{when_h}", "when": fx.ago(hours=when_h), "dir": direction, "type": mtype,
         "source": source, "status": status}
    if text:
        d["text"] = text
    return d


class MessageRules(unittest.TestCase):
    def test_automation_is_not_a_reply(self):
        f = score.msg_facts([m(4, "outbound", source="workflow"), m(5, "inbound")], NOW)
        self.assertIsNotNone(f["unanswered"])
        self.assertAlmostEqual(f["unanswered_hours"], 5, places=3)

    def test_joey_text_answers(self):
        f = score.msg_facts([m(4, "outbound", source="app"), m(5, "inbound")], NOW)
        self.assertIsNone(f["unanswered"])

    def test_api_send_counts_as_joey(self):
        # drafts Joey approves go out through the listener (API)
        f = score.msg_facts([m(4, "outbound", source="api"), m(5, "inbound")], NOW)
        self.assertIsNone(f["unanswered"])

    def test_call_attempt_answers_but_cancelled_does_not(self):
        f = score.msg_facts([m(4, "outbound", "TYPE_CAMPAIGN_CALL", "workflow", "no-answer"), m(5, "inbound")], NOW)
        self.assertIsNone(f["unanswered"])
        f = score.msg_facts([m(4, "outbound", "TYPE_CAMPAIGN_CALL", "workflow", "canceled"), m(5, "inbound")], NOW)
        self.assertIsNotNone(f["unanswered"])

    def test_missed_inbound_call_wants_a_call_back(self):
        f = score.msg_facts([m(2, "inbound", "TYPE_CALL", None, "no-answer")], NOW)
        self.assertEqual(score.channel_of(f["unanswered"]), "missed call")
        f = score.msg_facts([m(2, "inbound", "TYPE_CALL", None, "completed")], NOW)
        self.assertIsNone(f["unanswered"])

    def test_activity_and_auto_reply_ignored(self):
        f = score.msg_facts([m(1, "outbound", "TYPE_ACTIVITY_OPPORTUNITY"),
                             m(2, "inbound", "TYPE_EMAIL", text="Automatic reply: out of office")], NOW)
        self.assertIsNone(f["unanswered"])
        self.assertIsNone(f["last_joey"])

    def test_times_compared_as_times(self):
        # 05:00-05:00 is 10:00Z, after Joey's 09:30Z text, so it is unanswered even though it sorts first as text
        msgs = [{"id": "a", "when": "2026-11-02T05:00:00-05:00", "dir": "inbound", "type": "TYPE_SMS"},
                {"id": "b", "when": "2026-11-02T09:30:00.000Z", "dir": "outbound", "type": "TYPE_SMS", "source": "app"}]
        self.assertEqual(score.msg_facts(msgs, NOW)["unanswered"]["id"], "a")

    def test_stop_is_an_opt_out(self):
        self.assertTrue(score.msg_facts([m(1, "inbound", text="STOP")], NOW)["opted_out"])
        self.assertFalse(score.msg_facts([m(1, "inbound", text="Stop by Tuesday?")], NOW)["opted_out"])


class MemoryFields(unittest.TestCase):
    PIC = ("Asked for: evenings (9/21 call). Waiting on us: Loom with case studies, promised 9/14, Joey; "
           "county license question, since 10/24, Joey; check back after the weekend, since 10/30, you. "
           "How they reach back: answers texts. Situation: 6 beds, 2 empty. "
           "Offer 10/5 call: $6K for 90 days. Offer 10/20 call: not pitched. Zone: Pacific, area code.")

    def test_picture_parts(self):
        p = score.parse_picture(self.PIC)
        self.assertTrue(p["asked_for"].startswith("evenings"))
        self.assertEqual(len(p["offers"]), 2)
        self.assertTrue(p["zone"].startswith("Pacific"))
        self.assertTrue(score.pitched(p["offers"]))
        self.assertFalse(score.pitched(["Offer 10/20 call: not pitched"]))

    def test_waiting_items_and_owner(self):
        items = score.parse_waiting(score.parse_picture(self.PIC)["waiting"], NOW)
        self.assertEqual([i["who"] for i in items], ["Joey", "Joey", "agent"])
        self.assertEqual(items[0]["date"], "2026-09-14")
        self.assertEqual(items[0]["age_days"], 49)

    def test_owed_field_entries(self):
        got = score.parse_owed_field("2026-10-20: send the Loom; 2026-11-10: check back after opening", NOW)
        self.assertEqual([(g["date"], g["age_days"]) for g in got], [("2026-10-20", 13), ("2026-11-10", -8)])
        self.assertEqual(score.parse_owed_field("call her about pricing", NOW)[0]["date"], None)
        self.assertEqual(score.parse_owed_field("", NOW), [])
        self.assertEqual(score.parse_owed_field("None.", NOW), [])
        self.assertEqual(score.parse_owed_field("2026-10-28: nothing owed", NOW), [])
        self.assertEqual(score.parse_waiting("none yet.", NOW), [])

    def test_owed_items_merge_and_due(self):
        fields = {"owed": "2026-09-14: send the Loom with case studies\n2026-12-01: home opens, check back",
                  "picture": self.PIC}
        items = score.owed_items(fields, NOW)
        texts = [i["text"] for i in items]
        self.assertEqual(len([t for t in texts if "Loom" in t]), 1)       # same promise once
        self.assertTrue(any("county license" in t for t in texts))
        self.assertFalse(any("weekend" in t for t in texts))              # the agent's own promise is not Joey's
        future = next(i for i in items if "opens" in i["text"])
        self.assertFalse(future["due"])
        self.assertEqual(items[0]["age_days"], 49)                        # oldest first

    def test_loose_dates(self):
        self.assertEqual(score.parse_loose_date("promised Sept 14", NOW), dt.date(2026, 9, 14))
        self.assertEqual(score.parse_loose_date("since 12/30", NOW), dt.date(2025, 12, 30))   # not in the future
        self.assertEqual(score.parse_loose_date("24/7 care", NOW), None)

    def test_codes(self):
        self.assertEqual(score.lead_code({"email_code": "24"}, ["email-reply"]), "E24")
        self.assertEqual(score.lead_code({"reply_code": "41", "email_code": "3"}, ["leadsuite"]), "41")
        self.assertEqual(score.lead_code({"partner_code": "7"}, []), "P7")
        self.assertEqual(score.lead_code({}, []), "")

    def test_deadline(self):
        d = score.deadline_info("2026-11-18T20:00", NOW)
        self.assertEqual(d["days_left"], 16)
        self.assertFalse(d["passed"])
        self.assertEqual(d["label"], "Wed Nov 18, 8pm")
        late = score.deadline_info("2026-11-18T20:00", dt.datetime(2026, 11, 19, 2, 0, tzinfo=dt.timezone.utc))
        self.assertTrue(late["passed"])

    def test_meetings_skip_cancelled_ahead(self):
        evs = [{"contactId": "c", "start": fx.ahead(2), "status": "cancelled"},
               {"contactId": "c", "start": fx.ago(days=3), "status": "noshow"},
               {"contactId": "c", "start": fx.ahead(4), "status": "confirmed", "deleted": True},
               {"contactId": "x", "start": fx.ahead(1), "status": "confirmed"}]
        past, future = score.meetings_for("c", evs, NOW)
        self.assertEqual(future, [])
        self.assertEqual([p["status"] for p in past], ["noshow"])

    def test_scrub(self):
        self.assertEqual(score.scrub("call 555-201-4477 or (555) 201 4477 or a.b@example.org"), "call [phone] or [phone] or [email]")


class ValueShapes(unittest.TestCase):
    def test_numeric_codes(self):
        self.assertEqual(score.lead_code({"reply_code": 41.0}, []), "41")
        self.assertEqual(score.lead_code({"email_code": 7, "reply_code": ""}, ["email-reply"]), "E7")

    def test_checkbox_lists(self):
        c = {"id": "c", "firstName": "Pat", "lastName": "Example", "tags": []}
        facts = {"opted_out": False}
        self.assertEqual(score.is_excluded(c, {"test": ["No"]}, facts, set(), None, "1"), "")
        self.assertEqual(score.is_excluded(c, {"test": ["Yes"]}, facts, set(), None, "1"), "test")
        self.assertEqual(score.is_excluded(c, {}, facts, set(), None, "1", {"client"}), "client stage")

    def test_money_as_text(self):
        self.assertEqual(score.num("$4,500"), 4500.0)
        self.assertEqual(score.num(None), 0.0)
        self.assertEqual(score.num("n/a"), 0.0)


class StageRules(FakeGHL):
    def stage_id(self, raw, name, pipe="leadsuite"):
        p = next(p for p in raw["pipelines"] if p["key"] == pipe)
        return next(s["id"] for s in p["stages"] if s["name"] == name)

    def test_dead_stage_is_not_deciding(self):
        raw = self.raw()
        o2 = next(o for o in raw["opportunities"] if o["id"] == "o2")
        o2["stageId"] = self.stage_id(raw, "Not Interested")
        d = self.by_code(score.build(raw, now=NOW))
        self.assertEqual(d["12"]["buckets"], ["owed"])        # what is owed stays, the pitch does not

    def test_said_no_to_price_raise_is_not_deciding(self):
        raw = self.raw()
        raw["contacts"]["cDecide02"]["tags"].append("price-raise-no")
        d = self.by_code(score.build(raw, now=NOW))
        self.assertEqual(d["12"]["buckets"], ["owed"])
        self.assertNotIn("price raise", d["12"]["chips"])

    def test_client_stage_is_left_off(self):
        raw = self.raw()
        p = next(p for p in raw["pipelines"] if p["key"] == "email")
        p["stages"].append({"id": "emClient", "name": "Client"})
        next(o for o in raw["opportunities"] if o["id"] == "o4")["stageId"] = "emClient"
        self.assertNotIn("E24", self.by_code(score.build(raw, now=NOW)))

    def test_no_show_event_means_rebook(self):
        raw = self.raw()
        raw["events"].append({"id": "e9", "calendarId": fx.CAL, "contactId": "cDone0009", "start": fx.ago(days=2),
                              "end": fx.ago(days=2), "status": "noshow", "deleted": False, "title": "x"})
        d = self.by_code(score.build(raw, now=NOW))
        self.assertEqual(d["60"]["buckets"], ["rebook"])

    def test_agent_stage_booked_is_not_deciding(self):
        raw = self.raw()
        raw["contacts"]["cDecide02"]["fields"]["stage"] = "booked"
        d = self.by_code(score.build(raw, now=NOW))
        self.assertNotIn("deciding", d["12"]["buckets"])

    def test_price_raise_text_names_their_time(self):
        h = {f["key"]: f for f in self.desk()["health"]}
        self.assertEqual(h["price_raise"]["text"], "Price raise deadline in 16 days: Wed Nov 18, 8pm their time.")

    def test_hidden_leads_leave_the_counted_flags(self):
        desk = self.desk()
        e24 = next(l for l in desk["items"] if l["code"] == "E24")
        e24["drafts"] = {"hide": "answered in Gmail"}
        score.apply_hides(desk)
        h = {f["key"]: f for f in desk["health"]}
        self.assertEqual((h["unanswered"]["level"], h["unanswered"]["count"]), ("ok", 0))
        self.assertEqual((h["stale_replied"]["level"], h["stale_replied"]["codes"]), ("ok", []))
        e24["drafts"] = {}
        score.apply_hides(desk)                                   # idempotent: un-hiding brings it back
        h = {f["key"]: f for f in desk["health"]}
        self.assertEqual(h["unanswered"]["codes"], ["E24"])


class DeskTest(FakeGHL):
    def test_buckets(self):
        d = self.by_code(self.desk())
        self.assertEqual(d["41"]["buckets"], ["hot"])
        self.assertEqual(sorted(d["12"]["buckets"]), ["deciding", "owed"])
        self.assertEqual(d["7"]["buckets"], ["rebook"])
        self.assertEqual(d["E24"]["buckets"], ["stale_replied"])
        self.assertEqual(d["Jordan"]["buckets"], ["warm_referral"])
        for gone in ("99", "30", "55", "60"):        # test contact, parked, booked, answered
            self.assertNotIn(gone, d)

    def test_reasons_and_waiting(self):
        d = self.by_code(self.desk())
        self.assertEqual(d["41"]["why"], ["Wrote by text 5 hours ago. No reply from you yet."])
        self.assertEqual(d["41"]["waiting"], "5 hours")
        self.assertIn("On the price raise list, 16 days left.", d["12"]["why"][0])
        self.assertEqual(d["12"]["waiting"], "6 days")
        self.assertIn("pitched", d["12"]["chips"])
        self.assertIn("Waiting 13 days", d["12"]["why"][1])
        self.assertEqual(d["7"]["why"], ["Missed the meeting 3 days ago. Not rebooked."])
        self.assertEqual(d["E24"]["suggest"], ["email"])
        self.assertEqual(d["41"]["suggest"], ["sms"])

    def test_said_is_scrubbed(self):
        d = self.by_code(self.desk())
        self.assertNotIn("555", d["41"]["said"]["text"])
        self.assertNotIn("@", d["41"]["said"]["text"])

    def test_rank_closest_to_money_first(self):
        order = [l["code"] or l["first"] for l in self.desk()["items"]]
        self.assertEqual(order, ["41", "12", "7", "E24", "Jordan"])

    def test_health(self):
        desk = self.desk()
        h = {f["key"]: f for f in desk["health"]}
        self.assertEqual(h["meetings_next7"]["count"], 1)            # cancelled and other calendars left out
        self.assertEqual(h["meetings_next7"]["level"], "ok")
        self.assertEqual(h["last_new_lead"]["count"], 2)
        self.assertEqual(h["stale_replied"]["codes"], ["E24"])
        self.assertEqual(h["unanswered"]["level"], "red")
        self.assertEqual(h["unanswered"]["codes"], ["E24"])
        self.assertEqual(h["price_raise"]["count"], 16)
        self.assertEqual(desk["health"][0]["level"], "red")         # red first
        self.assertEqual(desk["top"], {"call_today": 2, "owed_items": 2, "booked_next_7": 1})

    def test_no_meetings_is_red(self):
        raw = self.raw()
        raw["events"] = []
        h = {f["key"]: f for f in score.build(raw, now=NOW)["health"]}
        self.assertEqual(h["meetings_next7"]["level"], "red")

    def test_routines_flag(self):
        desk = self.desk(routines=[{"name": "Follow up agent", "status": "FAILED"}, {"name": "Brief", "status": "SUCCEEDED"}])
        h = {f["key"]: f for f in desk["health"]}
        self.assertEqual(h["routines"]["level"], "red")
        self.assertIn("Follow up agent", h["routines"]["text"])
        score.apply_routines(desk, {"unavailable": "no list_triggers tool"})
        h = {f["key"]: f for f in desk["health"]}
        self.assertEqual(h["routines"]["level"], "info")

    def test_skip_codes_and_cap(self):
        raw = self.raw()
        raw["skip_codes"] = ["41"]
        desk = score.build(raw, now=NOW, cap=2)
        codes = [l["code"] for l in desk["items"]]
        self.assertNotIn("41", codes)
        self.assertEqual(desk["cap"], 2)

    def test_deadline_passed_drops_price_raise(self):
        raw = self.raw()
        raw["deadline_et"] = "2026-11-01T20:00"
        desk = score.build(raw, now=NOW)
        self.assertNotIn("price_raise", [f["key"] for f in desk["health"]])
        d = self.by_code(desk)
        self.assertNotIn("price raise", d["12"]["chips"])

    def test_brief_is_small(self):
        b = score.brief(self.desk())
        self.assertEqual(len(b["leads"]), 5)
        lead = b["leads"][1]
        self.assertIn("context", lead)
        self.assertEqual(lead["context"]["offers"], ["Offer 10/27 call: $4,500 for 90 days, ad spend $60/day."])
        self.assertEqual(len(lead["context"]["plan_log"]), 2)


if __name__ == "__main__":
    unittest.main()
