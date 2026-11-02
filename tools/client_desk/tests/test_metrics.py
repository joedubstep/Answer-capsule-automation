"""Who is who, and every number on the page, on synthetic data with known answers."""
from tools.client_desk import metrics as M
from tools.client_desk.tests.base import FakeGHL
from tools.client_desk.tests import fixtures as fx


class Classify(FakeGHL):
    def test_kinds(self):
        _, _, cls = self.built()
        kind = {cid: v["kind"] for cid, v in cls.items()}
        for cid in (fx.ALERT, "staff1", "userph", "test1"):
            self.assertEqual(kind[cid], "internal", cid)
        for cid in ("fam1", "fam2", "fam3", "fam4"):
            self.assertEqual(kind[cid], "family", cid)
        for cid in ("p1", "p2", "p3", "p4", "p5", "p6", "p7"):
            self.assertEqual(kind[cid], "partner", cid)
        self.assertEqual(kind["job1"], "not_family")
        for cid in ("u1", "u2n", "u3", "u4", "u5", "u6", "w0", "w1", "w2", "old1"):
            self.assertEqual(kind[cid], "unknown_caller", cid)

    def test_partner_with_family_deal_is_not_a_family(self):
        # the AGC collector's known bug: a tagged referral partner with a deal in the family pipeline
        _, desk, cls = self.built()
        self.assertEqual(cls["p8"]["kind"], "partner")
        self.assertEqual(desk["families"]["total"], 4)

    def test_before_start(self):
        raw = self.raw()
        p = dict(self.profile(), since="2026-10-20")
        cls = M.classify(raw, p)
        self.assertEqual(cls["fam2"]["kind"], "before_start")   # added 20 days before Nov 6
        self.assertEqual(cls["fam1"]["kind"], "family")


class Numbers(FakeGHL):
    def test_families(self):
        _, desk, _ = self.built()
        f = desk["families"]
        self.assertEqual(f["total"], 4)
        self.assertEqual(f["new_week"], 2)
        self.assertEqual(f["new_by_way"], {"website": 1, "text": 1})
        self.assertEqual(f["speed_week_min"], 4.0)
        self.assertEqual(f["speed_week_n"], 1)
        self.assertEqual(f["speed_month_n"], 2)
        self.assertEqual(f["speed_month_min"], 2.0)
        self.assertEqual(f["reached_week"], 1)
        self.assertEqual(f["unknown_callers"], 10)
        self.assertEqual(f["unknown_callers_week"], 9)

    def test_tours_and_move_ins(self):
        _, desk, _ = self.built()
        t, mi = desk["tours"], desk["move_ins"]
        self.assertEqual(t["booked_week"], 1)
        self.assertEqual(t["upcoming"], 1)
        self.assertEqual(t["toured_to_date"], 2)          # fam3 on the calendar, fam2 by deal stage only
        self.assertEqual(t["toured_calendar"], 1)
        self.assertEqual(t["toured_stage_only"], 1)
        self.assertEqual(t["held_week"], 2)
        self.assertEqual(t["not_counted"], 0)             # the alert contact's test tour is dropped before counting
        self.assertEqual(t["calendar_events"], 2)
        self.assertEqual(mi["to_date"], 1)
        self.assertEqual(mi["week"], 1)
        self.assertEqual(desk["deciding"], 1)             # fam2: post-tour, thinking it over

    def test_partners(self):
        _, desk, _ = self.built()
        pa = desk["partners"]
        self.assertEqual(pa["total"], 7)
        by = {r["name"]: (r["total"], r["open"], r["lost"]) for r in pa["stages"]}
        self.assertEqual(by["Not a Fit"], (1, 0, 1))
        self.assertEqual(by["To Call"], (1, 1, 0))
        self.assertEqual(sum(r["total"] for r in pa["stages"]), 7)
        self.assertEqual(pa["on_weekly_list"], 3)
        self.assertEqual(pa["sent_referral"], 1)
        self.assertEqual(pa["moves"]["moved"], 1)
        self.assertEqual(pa["moves"]["by_stage"], {"Sent a Referral": 1})
        self.assertEqual(pa["touches"], {"touches": 3, "partners_touched": 2, "partners_replied": 1})

    def test_activity_skips_internal_and_robocalls(self):
        _, desk, _ = self.built()
        a = desk["activity"]
        self.assertEqual(a["calls"], 2)
        self.assertEqual(a["calls_by_hand"], 1)
        self.assertEqual(a["texts"], 1)                   # the 30 texts to Joey's alert contact never count
        self.assertEqual(a["emails"], 2)
        self.assertEqual(a["calls_answered"], 0)          # answered robocalls are not "calls from families"

    def test_unanswered(self):
        _, desk, _ = self.built()
        un = {u["cid"]: u for u in desk["unanswered"]}
        self.assertEqual(set(un), {"fam4", "p6"})
        self.assertEqual(un["fam4"]["channel"], "text")
        self.assertEqual(un["p6"]["channel"], "email")
        self.assertEqual(un["p6"]["label"], "Harbor Social Work P6")
        self.assertNotIn("555", un["p6"]["preview"])      # digits in message text are masked

    def test_zero_is_zero(self):
        raw = self.raw()
        raw["messages"], raw["tour_events"] = [], []
        raw["opportunities"] = [o for o in raw["opportunities"] if o["pipelineId"] == fx.PAR]
        for c in raw["contacts"]:
            c["fields"].pop("tour_result", None)
        desk, _ = M.build(raw, self.profile(), self.now, "friday")
        self.assertEqual(desk["tours"]["toured_to_date"], 0)
        self.assertEqual(desk["move_ins"]["to_date"], 0)
        self.assertIsNone(desk["families"]["speed_week_min"])
        self.assertEqual(desk["activity"]["calls"], 0)


class Helpers(FakeGHL):
    def test_labels(self):
        raw = self.raw()
        cs = {c["id"]: c for c in raw["contacts"]}
        self.assertEqual(M.label(cs["p1"], "partner"), "Northside Hospital P1")
        self.assertEqual(M.label(cs["u1"], "unknown_caller"), "Caller 0001")
        self.assertTrue(M.label(cs["fam1"], "family").startswith("Pat E F"))
        self.assertEqual(M.family_code("abc"), "F" + __import__("hashlib").sha256(b"abc").hexdigest()[:6].upper())

    def test_median(self):
        self.assertEqual(M.median([3, 1, 2]), 2)
        self.assertEqual(M.median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(M.median([]))
