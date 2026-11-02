"""Every corpus case behaves as written: expected rules fire, guarded rules stay quiet."""
import collections
import unittest

from tools.copy_check.check import check
from tools.copy_check.tests.corpus import CASES


class TestCorpus(unittest.TestCase):
    def test_ids_unique(self):
        ids = [c["id"] for c in CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_cases(self):
        for c in CASES:
            o = c.get("opts") or {}
            r = check(c["text"], c["context"], o.get("require_link", False), o.get("require_optout", False),
                      o.get("template", False))
            got = collections.Counter(i["rule"] for i in r["issues"])
            with self.subTest(case=c["id"]):
                for rule, n in collections.Counter(c.get("expect", [])).items():
                    self.assertGreaterEqual(got[rule], n, "%s: expected %s x%d, got %s" % (c["id"], rule, n, dict(got)))
                for rule in c.get("absent", []):
                    self.assertEqual(got[rule], 0, "%s: %s should not fire: %s" % (
                        c["id"], rule, [i["match"] for i in r["issues"] if i["rule"] == rule]))
                if c.get("clean"):
                    self.assertEqual(r["issues"], [], c["id"])
                if "ok" in c:
                    self.assertEqual(r["ok"], c["ok"], "%s: %s" % (c["id"], [(i["rule"], i["severity"]) for i in r["issues"]]))

    def test_every_rule_is_exercised(self):
        """Each rule in rules.json is expected to fire by at least one corpus case."""
        from tools.copy_check.check import load_rules
        covered = {r for c in CASES for r in c.get("expect", [])}
        missing = [r["id"] for r in load_rules()["rules"] if r["id"] not in covered]
        self.assertEqual(missing, [], "rules with no positive corpus case")


if __name__ == "__main__":
    unittest.main()
