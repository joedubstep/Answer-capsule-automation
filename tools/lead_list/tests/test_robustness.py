"""Real-world file and web shapes the first version missed (review, 11/2): split state exports, HTML-table and
Excel 2003 "Excel" exports, .xlsx cells without references, broken servers, sites that answer only on www., a list
email cell with two addresses, a data folder without carehome.db. Synthetic data only."""
import argparse
import http.client
import json
import os
import shutil
import tempfile
import unittest
import urllib.request
from unittest import mock

from tools.lead_list import normalize, run, runway, tabular, web, website
from tools.lead_list.sources import fl_ahca
from tools.lead_list.tests import fixtures

ALIASES = {"name": ["Facility Name", "Name"], "beds": ["Licensed Beds", "Beds"], "city": ["City"]}


def args(**kw):
    a = dict(state="fl", file="", url="", data="", out="", min_beds=40, no_web=False, no_search=False, sites="",
             names="", minutes=5, workers=2, variants="AB", pace=None, date="2026-11-02")
    a.update(kw)
    return argparse.Namespace(**a)


class ExportFormats(unittest.TestCase):
    def test_html_table_saved_as_xls(self):
        html = ("<html><body><h1>Search results</h1><table><tr><td>menu</td></tr></table>"
                "<table><tr><th>Name</th><th>City</th><th>Licensed Beds</th></tr>"
                "<tr><td>Sunny &amp; Oaks Example</td><td>Example City</td><td>60</td></tr>"
                "<tr><td colspan=\"2\">Wide Example</td><td>41</td></tr></table></body></html>")
        headers, mapping, rows = tabular.load_rows(html.encode("cp1252"), ALIASES, "export.xls")
        self.assertEqual(mapping, {"name": "Name", "beds": "Licensed Beds", "city": "City"})
        self.assertEqual(rows[0], {"Name": "Sunny & Oaks Example", "City": "Example City", "Licensed Beds": "60"})
        self.assertEqual(rows[1]["Licensed Beds"], "41")  # a colspan keeps the later columns in place

    def test_excel_2003_xml(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?><?mso-application progid="Excel.Sheet"?>'
               '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
               'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Sheet1"><Table>'
               '<Row><Cell><Data ss:Type="String">Facility Name</Data></Cell>'
               '<Cell><Data ss:Type="String">Beds</Data></Cell></Row>'
               '<Row><Cell><Data ss:Type="String">Café Example</Data></Cell>'
               '<Cell><Data ss:Type="Number">52</Data></Cell></Row>'
               '<Row><Cell ss:Index="2"><Data ss:Type="Number">9</Data></Cell></Row>'
               '</Table></Worksheet></Workbook>')
        headers, mapping, rows = tabular.load_rows(xml.encode("utf-8"), ALIASES, "export.xls")
        self.assertEqual(rows[0], {"Facility Name": "Café Example", "Beds": "52"})
        self.assertEqual(rows[1], {"Facility Name": "", "Beds": "9"})

    def test_xlsx_cells_without_references(self):
        data = fixtures.xlsx_bytes([["Facility Name", "Beds"], ["A Example", 45]])
        import io
        import re
        import zipfile
        src = zipfile.ZipFile(io.BytesIO(data))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in src.namelist():
                body = src.read(n)
                if n.endswith("sheet1.xml"):
                    body = re.sub(rb' r="[A-Z]+\d+"', b"", body)
                z.writestr(n, body)
        headers, mapping, rows = tabular.load_rows(buf.getvalue(), ALIASES, "x.xlsx")
        self.assertEqual(rows, [{"Facility Name": "A Example", "Beds": "45"}])

    def test_empty_file_and_page_without_table(self):
        with self.assertRaises(ValueError):
            tabular.read_matrix(b"   \n", "empty.csv")
        with self.assertRaises(ValueError) as cm:
            tabular.read_matrix(b"<!DOCTYPE html><html><body>Please sign in</body></html>", "x.xls")
        self.assertIn("no data table", str(cm.exception))


class SplitExports(unittest.TestCase):
    """Florida refuses a statewide export it calls too large: county files in one folder must give the same batch."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = fixtures.make_engine_dir(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, rows):
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(fixtures.FL_HEADERS)
            w.writerows(rows)

    def test_folder_of_county_files_equals_one_statewide_file(self):
        one = fixtures.write_fl_csv(os.path.join(self.tmp, "fl.csv"))
        folder = os.path.join(self.tmp, "fl-files")
        os.makedirs(folder)
        self._write(os.path.join(folder, "area1.csv"), fixtures.FL_ROWS[:6])
        self._write(os.path.join(folder, "area2.csv"), fixtures.FL_ROWS[4:])  # rows 4 and 5 are in both
        with open(os.path.join(folder, "~$area1.csv"), "w") as f:  # an Excel lock file is skipped
            f.write("junk")
        quiet = dict(log=lambda *_: None)
        _, s1 = run.build(args(file=[one], data=self.data, out=os.path.join(self.tmp, "o1")),
                          fetch_fn=fixtures.FakeWeb(), **quiet)
        _, s2 = run.build(args(file=[folder], data=self.data, out=os.path.join(self.tmp, "o2")),
                          fetch_fn=fixtures.FakeWeb(), **quiet)
        self.assertEqual(s1["counts"], s2["counts"])
        self.assertEqual(s2["counts"]["on_list"], 10)
        self.assertIn("area1.csv, area2.csv", s2["source"])

    def test_cli_takes_repeated_file_flags(self):
        a = os.path.join(self.tmp, "a.csv")
        b = os.path.join(self.tmp, "b.csv")
        self._write(a, fixtures.FL_ROWS[:3])
        self._write(b, fixtures.FL_ROWS[3:])
        self.assertEqual(run.expand_files([a, b]), [a, b])
        with self.assertRaises(SystemExit):
            run.expand_files([os.path.join(self.tmp, "missing.csv")])
        empty = os.path.join(self.tmp, "empty-dir")
        os.makedirs(empty)
        with self.assertRaises(SystemExit):
            run.expand_files([empty])

    def test_unreadable_file_names_the_file(self):
        bad = os.path.join(self.tmp, "broken.xlsx")
        with open(bad, "wb") as f:
            f.write(b"PK\x03\x04 not really a zip")
        with self.assertRaises(SystemExit) as cm:
            run.load_sources(fl_ahca.SOURCE, [bad])
        self.assertIn("broken.xlsx", str(cm.exception))


class WebRobustness(unittest.TestCase):
    def test_broken_server_is_a_dead_site_not_a_crash(self):
        for exc in (http.client.IncompleteRead(b""), http.client.BadStatusLine("x"), ValueError("bad url")):
            with mock.patch.object(urllib.request, "urlopen", side_effect=exc):
                with self.assertRaises(OSError):
                    web.fetch("https://sunny.test/")
                with self.assertRaises(OSError):
                    web.fetch_bytes("https://sunny.test/list.xlsx")

    def test_unknown_charset(self):
        self.assertEqual(web._text("Café".encode("utf-8"), "utf8mb4"), "Café")

    def test_links_with_text(self):
        html = ('<a href="/files/list.xlsx">Adult Care Home Listing</a> <a href="/x.pdf"><b>PDF</b></a>'
                '<a href="/open-tag-only.csv">no close')
        got = web.links(html, "https://state.test/reports.htm", with_text=True)
        self.assertEqual(got[0], ("https://state.test/files/list.xlsx", "Adult Care Home Listing"))
        self.assertEqual(got[1], ("https://state.test/x.pdf", "PDF"))
        self.assertEqual(got[2][0], "https://state.test/open-tag-only.csv")

    def test_list_website_without_www(self):
        rec = {"official_name": "SUNNY OAKS EXAMPLE", "facility": "Sunny Oaks Example", "city": "Example City",
               "state": "FL", "phone": "+19045550101", "street": "1 MAIN ST", "list_website": "sunnyoaks.test"}
        fw = fixtures.FakeWeb(pages={"https://www.sunnyoaks.test": "<html>Sunny Oaks, call 904-555-0101</html>"})
        got = website.find(rec, fw, use_search=False)
        self.assertEqual(got["website"], "https://www.sunnyoaks.test")
        self.assertEqual(got["website_source"], "state license list, confirmed by phone on page")
        self.assertEqual(website.with_www("https://www.x.test/a"), "")


class Greetings(unittest.TestCase):
    def test_a_company_in_the_administrator_cell_is_not_a_name(self):
        from tools.lead_list import common
        for raw in ("ABC Senior Living LLC", "Sunny Oaks Management Inc", "Example Healthcare Group"):
            self.assertEqual(common.first_name(raw), "", raw)
            self.assertEqual(common.last_name(raw), "", raw)

    def test_last_first_lists(self):
        from tools.lead_list import common
        self.assertEqual(common.first_name("EXAMPLE PAT A", "last_first"), "Pat")
        self.assertEqual(common.last_name("EXAMPLE PAT", "last_first"), "Example")
        self.assertEqual(common.first_name("EXAMPLE, PAT", "last_first"), "Pat")  # a comma always wins
        self.assertEqual(common.first_name("EXAMPLE PAT"), "Example")  # the default reads first, last

    def test_accented_first_name(self):
        from tools.lead_list import common
        self.assertEqual(common.first_name("JOSÉ EXAMPLE"), "José")

    def test_source_order_reaches_the_record(self):
        src = fl_ahca.Florida()
        src.admin_order = "last_first"
        rec = normalize.normalize(src, {"Name": "A EXAMPLE HOME", "Administrator": "EXAMPLE ROBIN"},
                                  {"name": "Name", "administrator": "Administrator"})
        self.assertEqual((rec["first_name"], rec["last_name"]), ("Robin", "Example"))


class SmallFixes(unittest.TestCase):
    def test_list_email_cell_with_two_addresses(self):
        self.assertEqual(normalize.first_email("Admin@Sunny.test; info@sunny.test"), "admin@sunny.test")
        self.assertEqual(normalize.first_email("N/A"), "")

    def test_runway_without_the_database(self):
        tmp = tempfile.mkdtemp()
        data = fixtures.make_engine_dir(tmp)
        os.remove(os.path.join(data, "carehome.db"))
        st = runway.stats(data)
        self.assertIsNone(st["sendable_queued"])
        self.assertIn("cloud_state.py pull", st["note"])
        out = os.path.join(tmp, "out")
        code, s = run.build(args(file=fixtures.write_fl_csv(os.path.join(tmp, "fl.csv")), data=data, out=out),
                            fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        self.assertEqual(code, 0)
        with open(os.path.join(out, "fl", "HOW-TO-LOAD.md"), encoding="utf-8") as f:
            self.assertIn("no send pace", f.read())
        shutil.rmtree(tmp, ignore_errors=True)

    def test_review_command_prints_only_what_a_step_needs(self):
        tmp = tempfile.mkdtemp()
        data = fixtures.make_engine_dir(tmp)
        out = os.path.join(tmp, "out")
        run.build(args(file=fixtures.write_fl_csv(os.path.join(tmp, "fl.csv")), data=data, out=out),
                  fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        names = run.review_rows(os.path.join(out, "fl"), "names")
        self.assertEqual(len(names), 3)
        self.assertIn("fl-bayside-example-the-11900102 | The Bayside Example | Bayside Example (the)", names)
        # Quiet Pines has a website with no address on it, so it is not a WebSearch job: the list is empty
        self.assertEqual(run.review_rows(os.path.join(out, "fl"), "no-email"), [])
        sample = run.review_rows(os.path.join(out, "fl"), "sample", 10, seed=1)
        self.assertEqual(len(sample), 3)
        self.assertTrue(all(line.count(" | ") == 4 for line in sample))
        # with search off, River Bend has no website at all: that is the home step 6 asks Claude to look up
        out2 = os.path.join(tmp, "out2")
        run.build(args(file=os.path.join(tmp, "fl.csv"), data=data, out=out2, no_search=True),
                  fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        self.assertEqual(run.review_rows(os.path.join(out2, "fl"), "no-email"),
                         ["fl-river-bend-example-11900106 | River Bend Example | Example City | 55 beds | "
                          "phone +19045550206"])
        shutil.rmtree(tmp, ignore_errors=True)

    def test_review_csv_opens_in_excel(self):
        tmp = tempfile.mkdtemp()
        data = fixtures.make_engine_dir(tmp)
        out = os.path.join(tmp, "out")
        run.build(args(file=fixtures.write_fl_csv(os.path.join(tmp, "fl.csv")), data=data, out=out),
                  fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        with open(os.path.join(out, "fl", "review.csv"), "rb") as f:
            self.assertTrue(f.read(3) == b"\xef\xbb\xbf")
        with open(os.path.join(out, "fl", "summary.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["counts"]["queue_additions"], 3)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
