"""Website finder and published-email finder with a fake web (no network)."""
import unittest

from tools.lead_list import emails, web, website
from tools.lead_list.tests import fixtures


class Emails(unittest.TestCase):
    def test_extract_mailto_cloudflare_and_at_spelling(self):
        html = ('<a href="mailto:Pat.Example@Sunny.test?subject=hi">x</a> office [at] sunny.test '
                f'<span data-cfemail="{fixtures.cf_encode("tours@sunny.test")}"></span> '
                '<img src="logo@2x.png"> noreply@sunny.test you@example.com')
        self.assertEqual(emails.extract(html), ["tours@sunny.test", "pat.example@sunny.test", "office@sunny.test"])

    def test_classify_ranks(self):
        c = emails.classify
        self.assertEqual(c("pat.example@sunny.test", "www.sunny.test", "Pat", "Example"), 0)
        self.assertEqual(c("admissions@sunny.test", "sunny.test"), 2)
        self.assertEqual(c("info@sunny.test", "sunny.test"), 3)
        self.assertEqual(c("jdoe@sunny.test", "sunny.test"), 4)
        self.assertEqual(c("example.home.0000@gmail.com", "sunny.test"), 5)
        self.assertIsNone(c("web@designer.test", "sunny.test"))  # someone else's business domain

    def test_choose_prefers_named_then_list_then_role(self):
        found = [("info@sunny.test", "p1"), ("admissions@sunny.test", "p2"), ("pat@sunny.test", "p3")]
        got = emails.choose(found, "https://sunny.test", "", "Pat", "Example", "FL")
        self.assertEqual((got["email"], got["email_source"]), ("pat@sunny.test",
                                                               "the home's own website (named person)"))
        got = emails.choose(found[:2], "https://sunny.test", "owner@sunny.test", "", "", "FL")
        self.assertEqual((got["email"], got["email_source"]), ("owner@sunny.test", "FL state facility list"))
        got = emails.choose(found[:2], "https://sunny.test", "", "", "", "FL")
        self.assertEqual(got["email"], "admissions@sunny.test")
        self.assertEqual(emails.choose([("web@designer.test", "p")], "https://sunny.test")["email"], "")

    def test_site_walk_stops_at_a_named_address(self):
        fw = fixtures.FakeWeb()
        found = emails.site_emails("https://www.maplegrove.test", fw, fixtures.SITES["https://www.maplegrove.test"],
                                   first="Pat", last="Example")
        self.assertEqual(found[0][0], "pat.example@maplegrove.test")
        self.assertEqual(fw.calls, [])  # the home page already had a named address

    def test_pages_are_relative_to_the_home_page(self):
        fw = fixtures.FakeWeb(pages={})
        emails.site_emails("https://chain.test/communities/oak-example/index.html", fw, "<html></html>")
        self.assertTrue(fw.calls[0].startswith("https://chain.test/communities/oak-example/contact"))


class Website(unittest.TestCase):
    rec = {"official_name": "RIVER BEND EXAMPLE", "facility": "River Bend Example", "city": "Example City",
           "state": "FL", "phone": "+19045550206", "street": "600 RIVER RD", "list_website": ""}

    def test_confirm(self):
        self.assertEqual(website.confirm("Call 904-555-0206 today", self.rec), "phone on page")
        self.assertEqual(website.confirm("<p>600 River Road</p>", self.rec), "address on page")
        self.assertEqual(website.confirm("Another home, 601 River Rd", self.rec), "")

    def test_ddg_parse_and_directory_skip(self):
        urls = website.ddg_results(fixtures.DDG)
        self.assertEqual(urls, ["https://www.caring.com/x", "https://riverbend.test/"])
        self.assertTrue(website.is_directory(urls[0]))
        self.assertTrue(website.is_directory("https://info.ncdhhs.gov/dhsr/reports.htm"))
        self.assertFalse(website.is_directory("https://riverbend.test/"))

    def test_searched_site_needs_proof(self):
        got = website.find(dict(self.rec), fixtures.FakeWeb())
        self.assertEqual(got["website"], "https://riverbend.test/")
        self.assertEqual(got["website_source"], "DuckDuckGo search result, confirmed by phone on page")
        bad = dict(self.rec, phone="+19045550000", street="1 Other St")
        self.assertEqual(website.find(bad, fixtures.FakeWeb()), {})

    def test_list_site_counts_when_it_loads(self):
        r = dict(self.rec, list_website="quietpines.test", phone="", street="")
        got = website.find(r, fixtures.FakeWeb(), use_search=False)
        self.assertEqual(got["website_source"], "state license list")
        r2 = dict(self.rec, list_website="https://www.facebook.com/x")
        self.assertEqual(website.find(r2, fixtures.FakeWeb(pages={}), use_search=False), {})

    def test_search_switches_off_when_the_engine_pushes_back(self):
        from tools.lead_list.web import Page

        def angry(url, **kw):
            return Page(202, url, "<html>anomaly detected</html>")
        website.SEARCH.update(off=False, why="", fails=0)
        for _ in range(3):
            with self.assertRaises(website.SearchRefused):
                website.search(self.rec, angry)
        self.assertTrue(website.SEARCH["off"])
        with self.assertRaises(website.SearchRefused):  # stays off for the run, even when the engine would answer
            website.search(self.rec, fixtures.FakeWeb())
        website.SEARCH.update(off=False, why="", fails=0)

    def test_blocked_network_is_not_a_missing_site(self):
        with self.assertRaises(web.Blocked):
            website.find(dict(self.rec, list_website="sunny.test"), fixtures.FakeWeb(blocked=True))
        self.assertEqual(web.egress("https://x.test", fixtures.FakeWeb(blocked=True)), "blocked")


if __name__ == "__main__":
    unittest.main()
