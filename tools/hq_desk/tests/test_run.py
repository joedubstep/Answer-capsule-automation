import contextlib
import io
import json
import os

from tools.hq_desk import run
from tools.hq_desk.tests.base import FakeGHL


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_json(path):
    return json.loads(read_text(path))


class RunTest(FakeGHL):
    def go(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = run.main(["--location", "hq", "--now", "2026-11-02T11:00:00Z", "--out-dir", self.out, *args])
        return code, out.getvalue()

    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "out")
        os.environ.pop("HQ_DESK_COPY_CHECK", None)

    def test_dry_run_end_to_end(self):
        code, out = self.go("--dry-run")
        self.assertEqual(code, 0, out)
        for name in ("raw.json", "desk.json", "brief.json", "hq_desk.html", "sms.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        self.assertIn("WOULD TEXT: Desk: 1 new hot: 41 Pat.", out)
        self.assertIn("DRY RUN: nothing published, nothing texted.", out)

    def test_two_stages_with_drafts(self):
        code, out = self.go("--stage", "data")
        self.assertEqual(code, 0, out)
        brief = read_json(os.path.join(self.out, "brief.json"))
        lid = brief["leads"][0]["id"]
        with open(os.path.join(self.out, "drafts.json"), "w") as f:
            json.dump({lid: {"sms": "I can call at 3:30 today. Does that work?"}}, f)
        routines = os.path.join(self.tmp, "routines.json")
        with open(routines, "w") as f:
            json.dump([{"name": "Morning Sales Brief", "status": "FAILED"}], f)
        code, out = self.go("--stage", "page", "--routines", routines)
        self.assertEqual(code, 0, out)
        page = read_text(os.path.join(self.out, "hq_desk.html"))
        self.assertIn("I can call at 3:30 today. Does that work?", page)
        self.assertIn("Last run failed: Morning Sales Brief.", page)
        # a second run of the data stage clears the old drafts
        self.go("--stage", "data")
        self.assertFalse(os.path.exists(os.path.join(self.out, "drafts.json")))

    def test_held_draft_exit_1(self):
        self.go("--stage", "data")
        brief = read_json(os.path.join(self.out, "brief.json"))
        with open(os.path.join(self.out, "drafts.json"), "w") as f:
            json.dump({brief["leads"][0]["id"]: {"sms": "Quick one \u2014 call?"}}, f)
        code, out = self.go("--stage", "page")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"HELD 41 text: (no dashes|dash)")

    def test_bad_drafts_json_exit_1(self):
        self.go("--stage", "data")
        with open(os.path.join(self.out, "drafts.json"), "w") as f:
            f.write("{not json")
        code, out = self.go("--stage", "page")
        self.assertEqual(code, 1)
        self.assertIn("is not valid JSON", out)

    def test_page_before_data(self):
        code, out = self.go("--stage", "page")
        self.assertEqual(code, 2)


class RunNoAccessTest(FakeGHL):
    drop = ("contacts.json",)

    def test_no_access_exit_2(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = run.main(["--location", "hq", "--out-dir", os.path.join(self.tmp, "o")])
        self.assertEqual(code, 2)
        self.assertIn("NO ACCESS", out.getvalue())
