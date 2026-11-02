"""40+ bed filter, license type and status, and the dedupe against a synthetic engine data folder."""
import tempfile
import unittest

from tools.lead_list import dedupe, filters
from tools.lead_list.sources import fl_ahca, nc_dhsr
from tools.lead_list.tests import fixtures


def rec(**kw):
    base = {"id": "fl-new-example-11999999", "state": "FL", "facility": "New Example", "official_name": "NEW EXAMPLE",
            "city": "Example City", "phone": "+19045559999", "beds": 60, "type": "Assisted Living Facility",
            "status": "Licensed", "license": "11999999"}
    base.update(kw)
    return base


class Filter(unittest.TestCase):
    def test_forty_bed_line(self):
        src = fl_ahca.SOURCE
        self.assertEqual(filters.check(src, rec(beds=40)), (True, ""))
        self.assertEqual(filters.check(src, rec(beds=39)), (False, "under 40 beds (39)"))
        self.assertEqual(filters.check(src, rec(beds=None)), (False, "no bed count on the state list"))
        self.assertEqual(filters.check(src, rec(beds=12), min_beds=10)[0], True)

    def test_type_and_status(self):
        self.assertFalse(filters.check(fl_ahca.SOURCE, rec(type="Nursing Home"))[0])
        self.assertFalse(filters.check(fl_ahca.SOURCE, rec(status="Closed"))[0])
        self.assertFalse(filters.check(fl_ahca.SOURCE, rec(status="Pending Change of Ownership"))[0])
        self.assertTrue(filters.check(fl_ahca.SOURCE, rec(status=""))[0])
        ok, why = filters.check(nc_dhsr.SOURCE, rec(type="Family Care Home"))
        self.assertFalse(ok)
        self.assertIn("family care home", why)
        self.assertTrue(filters.check(nc_dhsr.SOURCE, rec(type="Adult Care Home"))[0])

    def test_apply_sets_decisions(self):
        recs = [rec(), rec(id="b", beds=10)]
        kept = filters.apply(fl_ahca.SOURCE, recs)
        self.assertEqual([r["id"] for r in kept], ["fl-new-example-11999999"])
        self.assertEqual(recs[1]["decision"], "exclude")


class Dedupe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixtures.make_engine_dir(tempfile.mkdtemp())
        cls.ix = dedupe.Index.load(cls.data)

    def test_index_reads_every_source(self):
        c = self.ix.counts
        self.assertEqual(c["carehome.db prospects"], 5)
        self.assertEqual(c["queue.json"], 4)
        self.assertEqual(self.ix.min_rank, -102)
        self.assertIn("owner@gone.test", self.ix.email)  # skipped homes count too

    def test_new_home_passes(self):
        self.assertEqual(self.ix.match(rec()), "")

    def test_same_license_number(self):
        why = self.ix.match(rec(id="fl-renamed-11900001", license="11900001", facility="Renamed Example",
                                official_name="RENAMED EXAMPLE"))
        self.assertIn("same license number as fl-sunny-oaks-example-11900001", why)

    def test_same_name_and_city(self):
        why = self.ix.match(rec(official_name="SUNNY OAKS EXAMPLE, LLC", city="Exampleton", license="x1"))
        self.assertIn("same name and city", why)

    def test_same_phone(self):
        why = self.ix.match(rec(phone="+19045550102", license="77777"))
        self.assertIn("same phone as fl-harbor-view-example-11900002", why)

    def test_same_email(self):
        self.assertIn("same email", self.ix.match(rec(), email="INFO@harborview.test"))

    def test_same_name_other_city_is_new(self):
        self.assertEqual(self.ix.match(rec(official_name="SUNNY OAKS EXAMPLE", city="Elsewhere")), "")

    def test_batch_pass_keeps_the_bigger_home(self):
        a = rec(id="fl-a-example-11888801", license="11888801", beds=50, phone="+19045558888")
        b = rec(id="fl-b-example-11888802", license="11888802", beds=90, phone="+19045558888")
        kept = dedupe.apply(self.ix, [a, b])
        self.assertEqual([r["id"] for r in kept], ["fl-b-example-11888802"])
        self.assertIn("repeated in this batch", a["reason"])

    def test_email_pass(self):
        a = rec(id="x1", beds=50, email="same@chain.test")
        b = rec(id="x2", beds=70, email="same@chain.test")
        c = rec(id="x3", beds=70, email="pat@sunnyoaks.test")
        kept = dedupe.apply_email(self.ix, [a, b, c])
        self.assertEqual([r["id"] for r in kept], ["x2"])
        self.assertIn("same email as x2", a["reason"])
        self.assertIn("already in the campaign", c["reason"])


if __name__ == "__main__":
    unittest.main()
