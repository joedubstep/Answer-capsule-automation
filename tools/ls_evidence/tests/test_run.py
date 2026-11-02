import contextlib
import io
import json
import os

from tools.ls_evidence import run
from tools.ls_evidence.tests.base import FakeGHL


class RunTest(FakeGHL):
    def go(self, *args, now="2026-11-08T11:00:00Z"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = run.main(["--location", "hq", "--now", now, "--out-dir", self.out, "--workers", "2", *args])
        return code, out.getvalue()

    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "out")

    def test_dry_run_end_to_end(self):
        code, out = self.go("--dry-run")
        self.assertEqual(code, 0, out)
        for name in ("raw.json", "evidence.json", "ls_evidence.html"):
            self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        self.assertIn("scoreboard: 3 of 30 qualified calls booked", out)
        self.assertIn("portal: 7 new lead rows, 0 changed; 3 new call rows, 0 changed", out)
        self.assertIn("(first run: everything finished is listed)", out)
        self.assertIn("sop: leads 68%", out)
        self.assertIn("DRY RUN: nothing published, nothing sent.", out)

    def test_prev_page_round_trip(self):
        self.go()
        prev = os.path.join(self.tmp, "prev.html")
        os.replace(os.path.join(self.out, "ls_evidence.html"), prev)
        code, out = self.go("--prev", prev)
        self.assertEqual(code, 0, out)
        self.assertIn("portal: 0 new lead rows, 0 changed; 0 new call rows, 0 changed", out)
        code, out = self.go("--prev", prev, now="2026-11-15T11:00:00Z")
        self.assertIn("portal: 1 new lead rows, 0 changed; 1 new call rows, 0 changed", out)

    def test_prev_without_state(self):
        prev = os.path.join(self.tmp, "prev.html")
        with open(prev, "w") as f:
            f.write("<title>Lead Suite Evidence</title>")
        code, out = self.go("--prev", prev)
        self.assertEqual(code, 0)
        self.assertIn("prev: no state found", out)

    def test_entered_through(self):
        code, out = self.go("--entered-through", "2026-10-25")
        self.assertEqual(code, 0)
        self.assertIn("portal: 4 new lead rows", out)
        with open(os.path.join(self.out, "evidence.json")) as f:
            self.assertEqual(json.load(f)["state"]["entered_through"], "2026-10-25")
        code, out = self.go("--entered-through", "Oct 25")
        self.assertEqual(code, 2)

    def test_probe_refused_on_hq(self):
        code, out = self.go("--probe", "5")
        self.assertEqual(code, 2)
        self.assertIn("never hq", out)

    def test_old_page_is_removed_first(self):
        os.makedirs(self.out, exist_ok=True)
        page = os.path.join(self.out, "ls_evidence.html")
        with open(page, "w") as f:
            f.write("old")
        os.environ["GHL_FAKE_DIR"] = os.path.join(self.tmp, "nothing-here")
        code, out = self.go()
        self.assertEqual(code, 2)
        self.assertIn("NO ACCESS", out)
        self.assertFalse(os.path.exists(page))
