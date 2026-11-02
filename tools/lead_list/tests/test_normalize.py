"""Normalizer: names, phones, time zones, addresses, ids and the per-state column mapping (synthetic rows)."""
import os
import tempfile
import unittest

from tools.lead_list import common, normalize, tabular
from tools.lead_list.sources import fl_ahca, nc_dhsr
from tools.lead_list.tests import fixtures


class FirstName(unittest.TestCase):
    def test_formats(self):
        cases = {"EXAMPLE, PAT A.": "Pat", "Pat A. Example, RN": "Pat", "Dr. Pat Example": "Pat",
                 "PAT EXAMPLE": "Pat", "Mary-Ann Example": "Mary-Ann", "Ed Example": "Ed",
                 "Pat Example (interim)": "Pat"}
        for raw, want in cases.items():
            self.assertEqual(common.first_name(raw), want, raw)

    def test_never_a_title_initial_or_placeholder(self):
        for raw in ("LVN", "Example, RN", "J. Example", "ADMINISTRATOR", "Vacant", "", "TBD", "admin@x.test",
                    "Owner", "123 Example"):
            self.assertEqual(common.first_name(raw), "", raw)

    def test_last_name(self):
        self.assertEqual(common.last_name("EXAMPLE, PAT"), "Example")
        self.assertEqual(common.last_name("Pat Example, RN"), "Example")


class HomeName(unittest.TestCase):
    def test_cleanups(self):
        self.assertEqual(common.display_home("SUNNY OAKS (THE)"), ("The Sunny Oaks", ""))
        self.assertEqual(common.display_home("Example Plaza, The")[0], "The Example Plaza")
        self.assertEqual(common.display_home("SUNNY OAKS ASSISTED LIVING, LLC")[0], "Sunny Oaks Assisted Living")
        self.assertEqual(common.display_home("MAPLE GROVE - MEMORY CARE")[0], "Maple Grove")
        self.assertEqual(common.display_home("ABC HOLDINGS LLC DBA SUNNY OAKS")[0], "Sunny Oaks")
        self.assertEqual(common.display_home("MCMINNVILLE MANOR")[0], "McMinnville Manor")
        self.assertEqual(common.display_home("SUNNY OAKS MANOR ALF, LLC")[0], "Sunny Oaks Manor")
        self.assertEqual(common.display_home("ROBIN'S PLACE")[0], "Robin's Place")

    def test_falls_back_to_your_home(self):
        for raw in ("Sunny Oaks Place B", "HCR Sunny Ctr", "Sunny Oaks #2",
                    "The Arbor At Sunny Oaks Of North Example County Retirement Village"):
            home, why = common.display_home(raw)
            self.assertEqual(home, common.YOUR_HOME, raw)
            self.assertTrue(why)

    def test_mixed_case_kept(self):
        self.assertEqual(common.nice_case("deVries Example Home"), "deVries Example Home")


class Basics(unittest.TestCase):
    def test_phone(self):
        self.assertEqual(common.phone_e164("(555) 210-2233 ext 4"), "+15552102233")
        self.assertEqual(common.phone_e164("1-904-555-0123"), "+19045550123")
        self.assertEqual(common.phone_e164("555-0123"), "")
        self.assertEqual(common.phone_e164("904-555-0123\n904-555-9999"), "+19045550123")

    def test_tz_split_states(self):
        self.assertEqual(common.tz_for("FL", "Escambia"), "America/Chicago")
        self.assertEqual(common.tz_for("FL", "Escambia County"), "America/Chicago")
        self.assertEqual(common.tz_for("FL", "Gulf", "Port St. Joe"), "America/New_York")
        self.assertEqual(common.tz_for("FL", "Gulf", "Wewahitchka"), "America/Chicago")
        self.assertEqual(common.tz_for("FL", "Duval"), "America/New_York")
        self.assertEqual(common.tz_for("NC", "Wake"), "America/New_York")
        self.assertEqual(common.tz_for("TN", "Knox"), "America/New_York")
        self.assertEqual(common.tz_for("TN", "Davidson"), "America/Chicago")
        self.assertEqual(common.tz_for("MI", "Gogebic"), "America/Chicago")

    def test_address_like_lead_facts(self):
        self.assertEqual(common.format_address("205 GILES AVE", "OMAHA", "tx", "75571-1234"),
                         "205 Giles Ave, Omaha, TX 75571")

    def test_ids_match_existing_shape(self):
        self.assertEqual(normalize.make_id("FL", "SUNNY OAKS (THE)", "11900001"), "fl-sunny-oaks-the-11900001")
        self.assertEqual(normalize.make_id("NC", "Oakwood Example", "HAL-001-001"), "nc-oakwood-example-hal001001")
        self.assertEqual(normalize.make_id("NC", "Oakwood Example", "", "Raleigh"), "nc-oakwood-example-raleigh")
        self.assertEqual(common.id_license_token("fl-sunny-oaks-the-11900001"), "11900001")
        self.assertEqual(common.id_license_token("oh-maple-example-assisted-living-ohl00001"), "ohl00001")
        self.assertEqual(common.id_license_token("ca-example-manor"), "")


class SourceMapping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_florida_export(self):
        path = fixtures.write_fl_csv(os.path.join(self.tmp, "fl.csv"))
        src = fl_ahca.SOURCE
        headers, mapping, rows = tabular.load_rows(path, src.all_aliases())
        self.assertEqual(mapping["license"], "File Number")
        self.assertEqual(mapping["beds"], "Licensed Beds")
        self.assertEqual(mapping["administrator"], "Administrator")
        recs = normalize.normalize_all(src, rows, mapping)
        maple = recs[0]
        self.assertEqual(maple["id"], "fl-maple-grove-example-11900101")
        self.assertEqual(maple["first_name"], "Pat")
        self.assertEqual(maple["beds"], 80)
        self.assertEqual(maple["phone"], "+19045550201")
        self.assertIn("column 'Phone Number'", maple["phone_source"])
        self.assertEqual(maple["care"], "assisted living facility, extended congregate care, limited nursing services")
        self.assertEqual(maple["address"], "100 Oak St, Example City, FL 32000")
        self.assertEqual(maple["tz"], "America/New_York")
        bay = recs[1]
        self.assertEqual(bay["home"], "The Bayside Example")
        self.assertEqual(bay["tz"], "America/Chicago")
        self.assertEqual(bay["first_name"], "Lee")
        self.assertEqual(recs[7]["first_name"], "")  # "ADMINISTRATOR" is not a name
        self.assertIn("not usable", recs[7]["first_name_source"])

    def test_north_carolina_xlsx_with_title_rows(self):
        path = fixtures.write_nc_xlsx(os.path.join(self.tmp, "nc.xlsx"))
        src = nc_dhsr.SOURCE
        headers, mapping, rows = tabular.load_rows(path, src.all_aliases())
        self.assertEqual(mapping["beds"], "Licensed Beds")
        self.assertEqual(mapping["memory"], "Special Care Unit Beds")
        recs = normalize.normalize_all(src, rows, mapping)
        self.assertEqual(len(recs), 4)
        oak = recs[0]
        self.assertEqual(oak["beds"], 96)
        self.assertEqual(oak["care"], "adult care home (assisted living), memory care (24 special care beds)")
        self.assertEqual(oak["first_name"], "Robin")
        self.assertEqual(oak["city"], "Raleigh")
        self.assertEqual(oak["tz"], "America/New_York")


class Tabular(unittest.TestCase):
    def test_json_records_and_arcgis(self):
        data = b'{"features": [{"attributes": {"Facility Name": "A Example", "Beds": 50}}]}'
        headers, mapping, rows = tabular.load_rows(data, {"name": ["Facility Name"], "beds": ["Beds"]}, "x.json")
        self.assertEqual(rows[0]["Beds"], "50")
        self.assertEqual(mapping, {"name": "Facility Name", "beds": "Beds"})

    def test_old_xls_is_refused_with_a_fix(self):
        with self.assertRaises(ValueError) as cm:
            tabular.read_matrix(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "x.xls")
        self.assertIn("save as", str(cm.exception))

    def test_tab_delimited_text(self):
        data = "Facility Name\tBeds\nA Example\t41\n".encode()
        headers, mapping, rows = tabular.load_rows(data, {"name": ["Facility Name"], "beds": ["Beds"]}, "x.txt")
        self.assertEqual(rows, [{"Facility Name": "A Example", "Beds": "41"}])


if __name__ == "__main__":
    unittest.main()
