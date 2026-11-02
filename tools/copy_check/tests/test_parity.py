"""Python vs JavaScript parity: the Copy Checker page must give the same answer as check.py.

Builds the real page, pulls its checker script out, runs it in node over the shared corpus plus a
seeded batch of mixed-up texts, and compares rule, severity, matched text, line, fix, ok and grade.
"""
import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest

from tools.copy_check import build_page
from tools.copy_check.check import check
from tools.copy_check.tests.corpus import CASES

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "parity_node.js")
NODE = shutil.which("node")
CONTEXTS = ("prospect_email", "prospect_sms", "client", "internal")


def fuzz_cases(n=300, seed=20261102):
    """Seeded mash-ups of corpus fragments: odd joins, line breaks, contexts and flags."""
    rnd = random.Random(seed)
    pieces = []
    for c in CASES:
        pieces += [p for p in c["text"].replace("\r", "").split("\n") if p.strip()]
        pieces += [s.strip() for s in c["text"].split(". ") if s.strip()]
    joins = [" ", "\n", "\n\n", ". ", ", ", "\r\n", " - ", "... ", "? ", "! ", "\n- ", chr(0xA0)]
    out = []
    for k in range(n):
        parts = rnd.sample(pieces, rnd.randint(1, 6))
        text = ""
        for p in parts:
            text += p + rnd.choice(joins)
        if rnd.random() < 0.3:
            text = text.lower()
        opts = {"require_link": rnd.random() < 0.2, "require_optout": rnd.random() < 0.2,
                "template": rnd.random() < 0.2}
        out.append({"id": "fuzz_%d" % k, "context": rnd.choice(CONTEXTS), "text": text, "opts": opts})
    return out


def py_result(c):
    o = c.get("opts") or {}
    r = check(c["text"], c["context"], o.get("require_link", False), o.get("require_optout", False),
              o.get("template", False))
    return {"id": c["id"], "ok": r["ok"], "grade": r["grade"], "counts": r["counts"],
            "issues": [{k: i[k] for k in ("rule", "severity", "match", "line", "fix")} for i in r["issues"]]}


@unittest.skipUnless(NODE, "node is not installed")
class TestParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="copycheck_parity_")
        cls.page = os.path.join(cls.tmp, "page.html")
        with open(cls.page, "w", encoding="utf-8") as f:
            f.write(build_page.build())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_node(self, cases):
        path = os.path.join(self.tmp, "corpus.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cases": cases}, f, ensure_ascii=True)
        p = subprocess.run([NODE, RUNNER, self.page, path], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, "node failed: " + p.stderr[-2000:])
        return json.loads(p.stdout)

    def compare(self, cases):
        js = self.run_node(cases)
        self.assertEqual(len(js), len(cases))
        for c, j in zip(cases, js):
            py = py_result(c)
            with self.subTest(case=c["id"]):
                self.assertEqual(py["ok"], j["ok"])
                self.assertEqual(py["counts"], j["counts"])
                if py["grade"] is None:
                    self.assertIsNone(j["grade"])
                else:
                    self.assertAlmostEqual(py["grade"], j["grade"], places=9)
                self.assertEqual(py["issues"], j["issues"])

    def test_corpus_matches(self):
        cases = [{"id": c["id"], "context": c["context"], "text": c["text"], "opts": c.get("opts") or {}}
                 for c in CASES]
        self.compare(cases)

    def test_corpus_in_every_context(self):
        cases = []
        for c in CASES:
            for ctx in CONTEXTS:
                cases.append({"id": c["id"] + "@" + ctx, "context": ctx, "text": c["text"],
                              "opts": {"require_link": True, "require_optout": True}})
        self.compare(cases)

    def test_fuzz_matches(self):
        self.compare(fuzz_cases())

    def test_odd_pastes_match_and_stay_fast(self):
        """The page's JavaScript gets the same answer on big odd pastes, and does not hang."""
        import time
        from tools.copy_check.tests.corpus import odd_inputs
        cases = [{"id": "odd_" + k, "context": ctx, "text": v, "opts": {"require_link": True, "require_optout": True}}
                 for k, v in odd_inputs().items() for ctx in ("prospect_sms", "client")]
        t0 = time.time()
        self.compare(cases)
        self.assertLess(time.time() - t0, 60, "the page checker is too slow on odd pastes")


if __name__ == "__main__":
    unittest.main()
