"""A named contact with nothing but rings is an unknown caller, not a family (Splendor live run, 11/2)."""
import unittest

from tools.client_desk import metrics as M

PROFILE = {"key": "sample", "since": "2026-10-01", "internal_contacts": []}


def raw(contacts, messages=(), opps=(), tours=(), fam="famPipe"):
    return {"contacts": list(contacts), "messages": list(messages), "opportunities": list(opps),
            "tour_events": list(tours), "family_pipeline_id": fam, "partner_pipeline_id": None, "internal": {}}


def contact(cid, named=True, source="", stage=""):
    return {"id": cid, "first": "Pat", "named": named, "tags": [], "source": source, "added": "2026-10-20T10:00:00Z",
            "phone": {}, "email": {}, "fields": {"agent_stage": stage}}


def call(cid, direction="inbound", src="", user=None):
    return {"id": "m" + cid, "cid": cid, "type": "TYPE_CALL", "dir": direction, "src": src, "user": user,
            "status": "no-answer", "when": "2026-10-21T15:00:00Z"}


class CallerIdOnly(unittest.TestCase):
    def kind(self, r, cid):
        return M.classify(r, PROFILE)[cid]["kind"]

    def test_named_with_only_missed_calls_is_unknown_caller(self):
        r = raw([contact("a")], [call("a")])
        self.assertEqual(self.kind(r, "a"), "unknown_caller")

    def test_inbound_text_makes_a_family(self):
        r = raw([contact("b")], [call("b"), {"id": "t", "cid": "b", "type": "TYPE_SMS", "dir": "inbound",
                                              "when": "2026-10-21T15:05:00Z"}])
        self.assertEqual(self.kind(r, "b"), "family")

    def test_family_deal_tour_or_form_source_make_a_family(self):
        self.assertEqual(self.kind(raw([contact("c")], opps=[{"contactId": "c", "pipelineId": "famPipe"}]), "c"), "family")
        self.assertEqual(self.kind(raw([contact("d")], tours=[{"contactId": "d"}]), "d"), "family")
        self.assertEqual(self.kind(raw([contact("e", source="Home website form")]), "e"), "family")

    def test_staff_reaching_out_by_hand_makes_a_family(self):
        r = raw([contact("f")], [call("f", direction="outbound", src="app", user="u1")])
        self.assertEqual(self.kind(r, "f"), "family")

    def test_workflow_auto_call_is_not_a_family_sign(self):
        r = raw([contact("g")], [call("g", direction="outbound", src="workflow", user="u1")])
        self.assertEqual(self.kind(r, "g"), "unknown_caller")

    def test_planner_judgment_wins(self):
        r = raw([contact("h", stage="talking")], [call("h")])
        self.assertEqual(self.kind(r, "h"), "family")


if __name__ == "__main__":
    unittest.main()
