"""End to end on synthetic data: build (FL CSV, NC XLSX) with a fake web, the blocked cases, runway, and the merge
that the PC session runs (dry run, write, layout kept, duplicates skipped)."""
import argparse
import json
import os
import tempfile
import unittest

from tools.lead_list import merge, run, runway, web
from tools.lead_list.tests import fixtures


def args(**kw):
    a = dict(state="fl", file="", url="", data="", out="", min_beds=40, no_web=False, no_search=False, sites="", names="",
             minutes=5, workers=2, variants="AB", pace=None, date="2026-11-02")
    a.update(kw)
    return argparse.Namespace(**a)


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = fixtures.make_engine_dir(self.tmp)
        self.out = os.path.join(self.tmp, "out")
        self.fl = fixtures.write_fl_csv(os.path.join(self.tmp, "fl.csv"))

    def _read(self, *p):
        with open(os.path.join(self.out, *p), encoding="utf-8") as f:
            return json.load(f) if p[-1].endswith(".json") else f.read()

    def test_florida_batch(self):
        code, s = run.build(args(file=self.fl, data=self.data, out=self.out), fetch_fn=fixtures.FakeWeb(),
                            log=lambda *_: None)
        self.assertEqual(code, 0)
        c = s["counts"]
        self.assertEqual(c["on_list"], 10)
        self.assertEqual(c["assisted_living_40_plus"], 7)  # tiny, closed and nursing left out
        self.assertEqual(c["after_dedupe"], 5)              # file number 11900001 and a known phone left out
        self.assertEqual(c["with_email"], 4)                # Quiet Pines shows no address
        self.assertEqual(c["queue_additions"], 3)           # Maple Grove North shares Maple Grove's inbox
        queue = self._read("fl", "queue_additions.json")
        by = {q["facility"]: q for q in queue}
        self.assertEqual(by["Maple Grove Example"]["email"], "pat.example@maplegrove.test")
        self.assertEqual(by["Bayside Example (the)"]["email"], "admissions@bayside.test")
        self.assertEqual(by["Bayside Example (the)"]["tz"], "America/Chicago")
        self.assertEqual(by["River Bend Example"]["email"], "frontdesk@riverbend.test")
        self.assertEqual(by["River Bend Example"]["first_name"], "")
        self.assertTrue(all(q["rank"] < -102 for q in queue))
        facts = self._read("fl", "lead_facts_additions.json")
        self.assertEqual(facts[by["River Bend Example"]["id"]]["website_source"],
                         "DuckDuckGo search result, confirmed by phone on page")
        review = self._read("fl", "review.csv")
        self.assertIn("under 40 beds (12)", review)
        self.assertIn("already in the campaign (same id fl-sunny-oaks-example-11900001)", review)
        self.assertIn("same phone as fl-harbor-view-example-11900002", review)
        self.assertIn("no published email found", review)
        self.assertIn("same email as fl-maple-grove-example-11900101", review)
        how = self._read("fl", "HOW-TO-LOAD.md")
        self.assertIn("push-local queue.json lead_facts.json build/prospects.json", how)
        self.assertIn("tools.lead_list.merge", how)
        self.assertEqual(s["runway"]["homes_with_email"], 3)

    def test_review_name_override_and_claude_found_site(self):
        names = os.path.join(self.tmp, "names.csv")
        with open(names, "w") as f:
            f.write("id,home\nfl-maple-grove-example-11900101,your home\n")
        sites = os.path.join(self.tmp, "sites.csv")
        with open(sites, "w") as f:
            f.write("id,website\nfl-river-bend-example-11900106,https://riverbend.test/\n")
        code, s = run.build(args(file=self.fl, data=self.data, out=self.out, names=names, sites=sites,
                                 no_search=True), fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        queue = {q["id"]: q for q in self._read("fl", "queue_additions.json")}
        self.assertEqual(queue["fl-maple-grove-example-11900101"]["home"], "your home")
        self.assertIn("at your home right now?", queue["fl-maple-grove-example-11900101"]["emails"]["1"]["body"])
        # with search off, River Bend is found only through the site Claude gave, and only because it shows the phone
        facts = self._read("fl", "lead_facts_additions.json")
        self.assertEqual(facts["fl-river-bend-example-11900106"]["website_source"],
                         "web search by Claude, confirmed by phone on page")

    def test_search_pushback_leaves_unsearched_homes_for_the_next_run(self):
        class Angry(fixtures.FakeWeb):
            def __call__(self, url, **kw):
                if "duckduckgo.com/html" in url and "assisted+living" not in url:
                    return web.Page(429, url, "rate limited")
                return super().__call__(url, **kw)
        code, s = run.build(args(file=self.fl, data=self.data, out=self.out, workers=1), fetch_fn=Angry(),
                            log=lambda *_: None)
        self.assertEqual(s["web_step"], "partial")
        cache = self._read("fl", "web_cache.json")
        self.assertNotIn("fl-river-bend-example-11900106", cache)  # no list site, never searched: retried later
        self.assertIn("fl-maple-grove-example-11900101", cache)     # list site, done
        self.assertIn("no email yet (web step partial)", self._read("fl", "review.csv"))

    def test_rerun_uses_the_web_cache(self):
        run.build(args(file=self.fl, data=self.data, out=self.out), fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        fw = fixtures.FakeWeb()
        code, s = run.build(args(file=self.fl, data=self.data, out=self.out), fetch_fn=fw, log=lambda *_: None)
        self.assertEqual(s["counts"]["queue_additions"], 3)
        self.assertEqual(fw.calls, [])

    def test_north_carolina_batch_no_web(self):
        nc = fixtures.write_nc_xlsx(os.path.join(self.tmp, "nc.xlsx"))
        code, s = run.build(args(state="nc", file=nc, data=self.data, out=self.out, no_web=True), log=lambda *_: None)
        self.assertEqual(code, 0)
        self.assertEqual(s["counts"]["on_list"], 4)
        self.assertEqual(s["counts"]["assisted_living_40_plus"], 2)
        self.assertEqual(s["counts"]["after_dedupe"], 1)  # Pine Ridge is already in by license number
        self.assertEqual(s["counts"]["queue_additions"], 0)  # NC lists no emails, and the web step was off
        self.assertIn("no email yet (web step skipped (--no-web))", self._read("nc", "review.csv"))

    def test_blocked_web_step(self):
        code, s = run.build(args(file=self.fl, data=self.data, out=self.out), fetch_fn=fixtures.FakeWeb(blocked=True),
                            log=lambda *_: None)
        self.assertEqual(code, 0)
        self.assertEqual(s["web_step"], "blocked")
        self.assertEqual(s["counts"]["queue_additions"], 0)
        self.assertIn("no email yet (web step blocked)", self._read("fl", "review.csv"))

    def test_blocked_download_writes_status_and_exits_3(self):
        orig = web.fetch_bytes
        web.fetch_bytes = lambda url, **k: (_ for _ in ()).throw(web.Blocked("state.test: Tunnel connection failed"))
        try:
            code, _ = run.build(args(url="https://state.test/list.xlsx", data=self.data, out=self.out),
                                log=lambda *_: None)
        finally:
            web.fetch_bytes = orig
        self.assertEqual(code, 3)
        self.assertIn("not built (network blocked)", self._read("fl", "RUN-STATUS.md"))
        self.assertFalse(os.path.exists(os.path.join(self.out, "fl", "queue_additions.json")))

    def test_no_file_and_no_link_explains_how_to_get_it(self):
        msgs = []
        code, _ = run.build(args(data=self.data, out=self.out), log=msgs.append)
        self.assertEqual(code, 2)
        self.assertIn("Export to Excel", msgs[-1])

    def test_unmapped_column_stops_with_the_headers(self):
        bad = os.path.join(self.tmp, "bad.csv")
        with open(bad, "w") as f:
            f.write("Facility Name,Something\nA Example,1\n")
        msgs = []
        code, _ = run.build(args(file=bad, data=self.data, out=self.out), log=msgs.append)
        self.assertEqual(code, 2)
        self.assertIn("no column for beds", msgs[-1])


class Runway(unittest.TestCase):
    def test_stats(self):
        data = fixtures.make_engine_dir(tempfile.mkdtemp())
        import datetime as dt
        st = runway.stats(data, dt.date(2026, 11, 2))
        self.assertEqual(st["queued"], 3)
        self.assertEqual(st["sendable_queued"], 1)  # only pat@ is valid among queued homes in the queue
        self.assertEqual(st["new_homes_last_7_days"], 4)
        self.assertAlmostEqual(st["pace_per_day"], 0.6)
        self.assertEqual(st["valid_rate_by_source"], {"website": 1.0, "state list": 1.0})


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = fixtures.make_engine_dir(self.tmp)
        self.out = os.path.join(self.tmp, "out")
        fl = fixtures.write_fl_csv(os.path.join(self.tmp, "fl.csv"))
        run.build(args(file=fl, data=self.data, out=self.out), fetch_fn=fixtures.FakeWeb(), log=lambda *_: None)
        self.batch = os.path.join(self.out, "fl")

    def _bytes(self, name):
        with open(os.path.join(self.data, name), "rb") as f:
            return f.read()

    def test_dry_run_writes_nothing(self):
        before = self._bytes("queue.json")
        self.assertEqual(merge.main(["--batch", self.batch, "--data", self.data]), 0)
        self.assertEqual(self._bytes("queue.json"), before)

    def test_write_appends_and_keeps_the_layout(self):
        before = {n: self._bytes(n) for n in ("queue.json", "lead_facts.json", os.path.join("build", "prospects.json"))}
        self.assertEqual(merge.main(["--batch", self.batch, "--data", self.data, "--write"]), 0)
        after = {n: self._bytes(n) for n in before}
        for n in before:
            # everything up to the last closing bracket is unchanged: the merge only adds entries
            self.assertTrue(after[n].startswith(before[n][:-3]), n)
            self.assertIn(b"\r\n", after[n])
            self.assertFalse(after[n].endswith(b"\n"))
        self.assertIn("Café".encode(), after["queue.json"])           # raw accents stay raw in queue.json
        queue = json.loads(after["queue.json"])
        self.assertEqual(len(queue), 7)
        self.assertEqual([q["rank"] for q in queue[4:]], [-103, -104, -105])
        self.assertTrue(any(n.startswith("backup-") for n in os.listdir(self.batch)))
        # a second merge finds every home already there
        p = merge.plan(self.batch, self.data)
        self.assertEqual(len(p["queue"]), 0)
        self.assertEqual(len(p["skipped"]), 3)

    def test_layout_round_trip_is_byte_identical(self):
        for name, d in (("queue.json", 1), ("lead_facts.json", 0), (os.path.join("build", "prospects.json"), 1)):
            path = os.path.join(self.data, name)
            before = self._bytes(name)
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
            merge._write(path, obj, merge._layout(path, d))
            self.assertEqual(self._bytes(name), before, name)


if __name__ == "__main__":
    unittest.main()
