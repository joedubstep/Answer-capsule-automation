"""The Copy Checker page builds, is self-contained, follows the brand, and Joey-facing docs pass the rules."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

from tools.copy_check import build_page
from tools.copy_check.check import check, compile_rules, load_rules

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DASHES = (chr(0x2012), chr(0x2013), chr(0x2014), chr(0x2015))
NOW = dt.datetime(2026, 11, 2, 19, 5, tzinfo=dt.timezone.utc)


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = build_page.build(now=NOW)

    def test_placeholders_replaced(self):
        for key in ("__RULES_JSON__", "__BUILT_AT__", "__RULE_COUNT__"):
            self.assertNotIn(key, self.html)
        self.assertIn("Last updated Nov 2, 2026 at 2:05 PM ET", self.html)
        self.assertIn("All %d rules" % len(load_rules()["rules"]), self.html)

    def test_embedded_rules_match_compiled(self):
        m = re.search(r'<script id="rules-data" type="application/json">(.*?)</script>', self.html, re.S)
        self.assertIsNotNone(m)
        data = m.group(1)
        self.assertNotIn("<", data)
        self.assertNotIn("&", data)
        self.assertEqual(json.loads(data), compile_rules(load_rules()))

    def test_self_contained(self):
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(self.html, r"<(?:img|iframe|object|embed)\b")
        self.assertNotIn("fetch(", self.html)
        self.assertIn("/* CHECKER START */", self.html)
        self.assertIn("/* CHECKER END */", self.html)

    def test_artifact_contract(self):
        self.assertIn("<title>Surven Copy Checker</title>", self.html[:8192])
        self.assertNotIn("<!doctype", self.html.lower())
        self.assertIn('name="claude:viewport-fit-sides"', self.html)
        self.assertIn("padding-left: max(16px, env(safe-area-inset-left, 0px))", self.html)
        self.assertIn("padding-right: max(16px, env(safe-area-inset-right, 0px))", self.html)
        self.assertIn("@media (prefers-color-scheme: dark)", self.html)
        self.assertIn(':root[data-theme="dark"]', self.html)
        self.assertRegex(self.html, r"body \{ background: var\(--cream\)")

    def test_brand_palette(self):
        for color in ("#f2eee3", "#faf7ef", "#4e6242", "#181b18", "#c8c1b1"):
            self.assertIn(color, self.html.lower())
        self.assertNotIn("#f78736", self.html.lower())

    def test_no_dashes_or_contact_details(self):
        self.assertFalse(any(d in self.html for d in DASHES), "literal em or en dash in the page")
        self.assertNotRegex(self.html, r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b")
        self.assertNotRegex(self.html, r"[\w.+-]+@[\w-]+\.[a-z]{2,}")

    def test_standalone(self):
        html = build_page.build(standalone=True, now=NOW)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertTrue(html.rstrip().endswith("</html>"))

    def test_cli_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "copy_checker.html")
            p = subprocess.run([sys.executable, "-m", "tools.copy_check.build_page", "--out", out], cwd=ROOT,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(os.path.getsize(out) > 20000)
            self.assertIn("wrote", p.stdout)


class TestDocsFollowRules(unittest.TestCase):
    """The files Joey and the routines read pass the checker too (no dashes, US English, no TLDR)."""

    FILES = ["tools/copy_check/README.md", ".claude/skills/copy_check/SKILL.md", "routines/copy_check.md"]

    def test_docs(self):
        for rel in self.FILES:
            path = os.path.join(ROOT, rel)
            with self.subTest(file=rel):
                self.assertTrue(os.path.exists(path), rel)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                self.assertFalse(any(d in text for d in DASHES), rel)
                res = check(text, "internal")
                blocks = [(i["rule"], i["match"]) for i in res["issues"] if i["severity"] == "block"]
                self.assertEqual(blocks, [], rel)


if __name__ == "__main__":
    unittest.main()
