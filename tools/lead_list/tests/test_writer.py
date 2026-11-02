"""Queue-entry writer against the real schema: key order, locked v3 copy, A/B, ranks, copy check, lead_facts and
prospects shapes. The engine contract is restated here (this repo cannot import the engine): carehome.cmd_load
reads id, email, facility, first_name, tz, rank; due_items/send_one read seq and emails[str(step)]; v3 has 4 steps
with step 3 {"pending": true}; day7 reads home; the A/B report reads variant."""
import unittest

from tools.lead_list import common, writer
from tools.lead_list.sources import fl_ahca

REAL_QUEUE_KEYS = ['id', 'email', 'facility', 'first_name', 'tz', 'rank', 'variant', 'seq', 'home', 'emails']
REAL_FACT_KEYS = ['facility', 'city', 'state', 'website', 'website_source', 'address', 'beds', 'beds_word', 'care',
                  'tz', 'census', 'open_beds', 'census_date', 'phone', 'phone_source']
REAL_PROSPECT_KEYS = ['id', 'facility', 'website', 'address', 'state', 'tz', 'care_type', 'beds', 'beds_source',
                      'private_pay', 'contact_name', 'contact_role', 'email', 'email_source', 'email_confidence',
                      'bant', 'personalization', 'status', 'flags', 'reason', 'sources', 'researched']
SEQ_V3 = {1: 0, 2: 2, 3: 6, 4: 13}  # surven_outreach/carehome.py


def rec(i=1, first="Pat", home="Sunny Oaks Example", beds=60, **kw):
    r = {"id": f"fl-home-example-1190{i:04d}", "email": f"pat{i}@home{i}.test", "facility": "Sunny Oaks Example",
         "official_name": "SUNNY OAKS EXAMPLE", "first_name": first, "home": home, "home_check": "",
         "tz": "America/New_York", "state": "FL", "city": "Example City", "address": "1 Main St, Example City, FL 32000",
         "beds": beds, "beds_word": "beds", "care": "assisted living facility", "phone": "+19045550100",
         "phone_source": "synthetic", "website": f"https://home{i}.test", "website_source": "state license list",
         "email_source": "the home's own website (named person)", "email_page": f"https://home{i}.test/contact",
         "admin_raw": "EXAMPLE, PAT", "license": f"1190{i:04d}", "licensee": "Example LLC"}
    r.update(kw)
    return r


class QueueEntry(unittest.TestCase):
    def test_exact_schema_and_locked_copy_variant_a(self):
        q = writer.queue_entry(rec(), "A", -500)
        self.assertEqual(list(q), REAL_QUEUE_KEYS)
        self.assertEqual(q["seq"], "v3")
        self.assertEqual(sorted(q["emails"]), ["1", "2", "3", "4"])
        self.assertEqual(len(q["emails"]), max(SEQ_V3))
        self.assertEqual(q["emails"]["1"], {"subject": "Do you have an open room?",
                                            "body": "Hi Pat, how many rooms are open at Sunny Oaks Example right "
                                                    "now?\n\nJoey"})
        self.assertEqual(q["emails"]["2"], {"body": "Hey, I just emailed you.\n\nJoey"})
        self.assertEqual(q["emails"]["3"], {"pending": True})
        self.assertEqual(q["emails"]["4"], {"body": "Hi Pat I'm closing this out and will stop emailing.\n\nJoey"})
        for k in ("id", "email", "facility", "first_name", "tz"):
            self.assertIsInstance(q[k], str)
        self.assertIsInstance(q["rank"], int)

    def test_variant_b_and_no_name(self):
        q = writer.queue_entry(rec(first=""), "B", -1)
        self.assertEqual(q["emails"]["1"]["body"],
                         "Hi, do you have any open rooms at Sunny Oaks Example right now?\n\nJoey")
        self.assertEqual(q["emails"]["4"]["body"], "I'm closing this out and will stop emailing.\n\nJoey")
        self.assertEqual(q["first_name"], "")

    def test_your_home(self):
        q = writer.queue_entry(rec(home=common.YOUR_HOME), "A", -1)
        self.assertEqual(q["emails"]["1"]["body"], "Hi Pat, how many rooms are open at your home right now?\n\nJoey")


class Assignments(unittest.TestCase):
    def test_variants_balanced_and_stable(self):
        ids = [f"fl-x-{i}" for i in range(101)]
        v = writer.assign_variants(ids)
        counts = {k: list(v.values()).count(k) for k in "AB"}
        self.assertLessEqual(abs(counts["A"] - counts["B"]), 1)
        self.assertEqual(v, writer.assign_variants(list(reversed(ids))))
        self.assertEqual(set(writer.assign_variants(ids, "A").values()), {"A"})

    def test_ranks_below_queue_bigger_first(self):
        r = writer.assign_ranks([rec(1, beds=50), rec(2, beds=120), rec(3, beds=80)], -6291)
        self.assertEqual(r["fl-home-example-11900002"], -6292)
        self.assertEqual(r["fl-home-example-11900003"], -6293)
        self.assertEqual(r["fl-home-example-11900001"], -6294)


class Build(unittest.TestCase):
    def test_build_outputs_real_shapes(self):
        recs = [rec(1), rec(2, first="", beds=90), rec(3, beds=45)]
        queue, facts, people = writer.build(recs, fl_ahca.SOURCE, -10, "2026-11-02")
        self.assertEqual(len(queue), 3)
        self.assertEqual([q["rank"] for q in queue], [-11, -12, -13])  # file order = send order
        self.assertEqual(list(facts[queue[0]["id"]]), REAL_FACT_KEYS)
        self.assertEqual(list(people[0]), REAL_PROSPECT_KEYS)
        self.assertEqual(people[0]["status"], "HOLD")
        self.assertIn("40+ beds (Joey 10/23)", people[0]["flags"][0])
        self.assertTrue(all(r["decision"] == "include" for r in recs))
        f = facts[queue[0]["id"]]
        self.assertIsNone(f["census"])
        self.assertEqual(f["census_date"], "")

    def test_copy_check_blocks_a_dash_in_the_name_and_falls_back(self):
        r = rec(home="Sunny Oaks \u2014 North")
        queue, facts, people = writer.build([r], fl_ahca.SOURCE, -1, "2026-11-02")
        self.assertEqual(queue[0]["home"], common.YOUR_HOME)
        self.assertIn("used 'your home'", r["home_check"])

    def test_every_written_body_passes_the_copy_checker(self):
        from tools.copy_check.check import check
        queue, _, _ = writer.build([rec(i, first=f) for i, f in enumerate(["Pat", "", "Lee", "Jo"], 1)],
                                   fl_ahca.SOURCE, -1, "2026-11-02")
        for q in queue:
            for step in ("1", "2", "4"):
                self.assertTrue(check(q["emails"][step]["body"], "prospect_email")["ok"])


if __name__ == "__main__":
    unittest.main()
