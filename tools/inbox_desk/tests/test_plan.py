import base64
import io
import json
import os
import re
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout

from tools.inbox_desk import minipdf
from tools.inbox_desk import plan

LINK = "https://start.example.com/booking-page-1"
FACTS = {"home": "Maple Example House", "city": "Sampletown", "state": "tx",
         "beds": {"value": "48", "source": "https://www.example-health.texas.gov/facility/1"},
         "care_type": {"value": "Assisted living and memory care", "source": "https://www.maple-example.com/care"}}


def pdf_text(raw):
    """Every text string drawn on the page (inflated content stream)."""
    m = re.search(rb"/Filter /FlateDecode >>\nstream\n(.*?)\nendstream", raw, re.S)
    ops = zlib.decompress(m.group(1)).decode("latin-1")
    return " ".join(re.findall(r"\((.*?)\) Tj", ops))


class Facts(unittest.TestCase):
    def test_sources(self):
        self.assertEqual(plan.source_kind("https://www.example.ca.gov/x"), "state license record")
        self.assertEqual(plan.source_kind("https://apps.example.state.ga.us/r"), "state license record")
        self.assertEqual(plan.source_kind("https://maple-example.com"), "the home's own website")
        for bad in ("https://www.caring.com/x", "https://www.aplaceformom.com/y", "https://facebook.com/z",
                    "https://www.google.com/maps/x", "ftp://example.gov/x", "maple-example.com", "",
                    "https://www.medicare.gov/care-compare/details/1"):
            self.assertIsNone(plan.source_kind(bad), bad)
        # a home's own .us site is not a state record; a state government .us site is
        self.assertEqual(plan.source_kind("https://maple-example.us/about"), "the home's own website")
        self.assertEqual(plan.source_kind("https://www.example.state.mn.us/x"), "state license record")

    def test_unverified_facts_are_dropped(self):
        f, dropped = plan.verified_facts({"home": "Maple", "beds": {"value": 40, "source": "https://www.seniorly.com/m"},
                                          "care_type": {"value": "Memory care"}, "state": "tx"})
        self.assertNotIn("beds", f)
        self.assertNotIn("care_type", f)
        self.assertEqual({d[0] for d in dropped}, {"beds", "care_type"})
        self.assertEqual(f["state"], "TX")
        f, dropped = plan.verified_facts({"home": "Maple", "beds": {"value": "lots", "source": "https://m.example.gov"}})
        self.assertEqual(dropped, [("beds", "not a number")])
        with self.assertRaises(ValueError):
            plan.verified_facts({"home": ""})

    def test_plan_words_follow_the_rules(self):
        steps = plan.load_steps()
        f, _ = plan.verified_facts(FACTS)
        w = plan.words(f, steps, LINK, "November 2, 2026")
        text = plan.visible_text(w)
        self.assertEqual(len(w["steps"]), 3)
        self.assertNotRegex(text, r"\$|\d+\s?%|guarantee|we call|we will call|care home|patients|\bleads?\b")
        self.assertIn("Licensed beds: 48", text)
        self.assertIn(LINK, text)
        from tools.inbox_desk.drafts import check
        r = check(text, "prospect_email", require_link=True)
        self.assertTrue(r["ok"], r["blocking"])


class Render(unittest.TestCase):
    def render(self, facts=FACTS, engine="mini", link=LINK):
        d = tempfile.mkdtemp()
        meta = plan.render(facts, d, engine=engine, booking_link=link, today="2026-11-02")
        return d, meta

    def test_mini_pdf_is_valid_and_small(self):
        d, meta = self.render()
        self.assertEqual(meta["engine"], "mini")
        with open(os.path.join(d, "plan.pdf"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"%PDF-1.4"))
        self.assertTrue(raw.rstrip().endswith(b"%%EOF"))
        self.assertLess(len(raw), 8000)
        self.assertEqual(raw.count(b"/Type /Page "), 1)
        # every xref offset points at its object
        xref = int(re.search(rb"startxref\n(\d+)", raw).group(1))
        self.assertTrue(raw[xref:].startswith(b"xref"))
        offs = [int(x) for x in re.findall(rb"(\d{10}) 00000 n", raw)]
        for n, off in enumerate(offs, 1):
            self.assertTrue(raw[off:].startswith(b"%d 0 obj" % n), n)
        words = pdf_text(raw)
        for s in ("Maple Example House", "Sampletown, TX", "November 2, 2026", "Licensed beds", "48",
                  "ONE THING YOU CAN TRY THIS WEEK", "Want to walk through it?"):
            self.assertIn(s, words)
        self.assertIn(LINK.encode(), raw)  # clickable link annotation
        with open(os.path.join(d, "plan.b64")) as f:
            self.assertEqual(base64.b64decode(f.read()), raw)
        self.assertEqual(meta["filename"], "Maple Example House plan.pdf")
        self.assertEqual(meta["mime"], "application/pdf")
        self.assertTrue(meta["copy"]["ok"])

    def test_html_has_brand_and_no_dropped_fact(self):
        facts = dict(FACTS, care_type={"value": "Memory care", "source": "https://www.caring.com/x"})
        d, meta = self.render(facts)
        with open(os.path.join(d, "plan.html")) as f:
            h = f.read()
        self.assertIn("#4e6242", h)
        self.assertIn("prefers-color-scheme", h)
        self.assertNotIn("<script", h)
        self.assertNotIn("Memory care", h)
        self.assertIn("state license record", h)
        self.assertEqual(meta["dropped"], [{"fact": "care_type", "why": "source is not a state record or the home's own site"}])

    def test_html_engine_fallback(self):
        d, meta = self.render(engine="html")
        self.assertEqual((meta["engine"], meta["mime"]), ("html", "text/html"))
        self.assertFalse(os.path.exists(os.path.join(d, "plan.pdf")))

    def test_long_name_still_one_page(self):
        facts = dict(FACTS, home="The Very Long Example Name Assisted Living And Memory Care Community Of Sampletown")
        d, meta = self.render(facts)
        with open(os.path.join(d, "plan.pdf"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"/Type /Page "), 1)
        self.assertTrue(meta["copy"]["ok"], meta["copy"])

    def test_missing_link_blocks(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "facts.json")
        with open(p, "w") as f:
            json.dump(FACTS, f)
        with redirect_stdout(io.StringIO()) as buf:
            rc = plan.main(["--facts", p, "--out-dir", d, "--engine", "mini", "--booking-link", "", "--date", "2026-11-02"])
        self.assertEqual(rc, 1)
        self.assertIn("BLOCK", buf.getvalue())

    def test_cli_ok_and_bad_facts(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "facts.json")
        with open(p, "w") as f:
            json.dump(FACTS, f)
        with redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(plan.main(["--facts", p, "--out-dir", d, "--engine", "mini", "--booking-link", LINK]), 0)
        self.assertIn("mini", buf.getvalue())
        with open(p, "w") as f:
            json.dump({"city": "x"}, f)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan.main(["--facts", p, "--out-dir", d, "--engine", "mini"]), 2)

    @unittest.skipUnless(os.environ.get("INBOX_DESK_TEST_CHROME"), "set INBOX_DESK_TEST_CHROME=1 to test the chrome engine")
    def test_chrome_engine(self):
        d, meta = self.render(engine="chrome")
        self.assertEqual(meta["engine"], "chrome")


class MiniPdf(unittest.TestCase):
    def test_wrap_and_clean(self):
        lines = minipdf.wrap("one two three four five six seven eight nine ten", 11, 60)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(minipdf.width(l, 11) <= 60 or " " not in l for l in lines))
        self.assertEqual(minipdf.clean("\u201cHi\u201d \u2014 ok"), '"Hi" - ok')
        page = minipdf.Page()
        page.text(10, 10, "a (b) \\ c")
        self.assertIn("a \\(b\\) \\\\ c", page.ops[0])


if __name__ == "__main__":
    unittest.main()
