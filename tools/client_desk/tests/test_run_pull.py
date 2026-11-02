"""End to end through the runner, the pull's privacy and discovery, and the collector patch proposal."""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tools.client_desk import pull, run, profile
from tools.client_desk.tests.base import FakeGHL
from tools.client_desk.tests import fixtures as fx

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(TOOL))


def run_main(args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run.main(args)
    return code, buf.getvalue()


class Runner(FakeGHL):
    def out(self):
        return os.path.join(self.tmp, "out")

    def test_friday_dry_run(self):
        code, log = run_main(["--client", "agc", "--mode", "friday", "--dry-run", "--now", fx.NOW.isoformat(),
                              "--out-dir", self.out()])
        self.assertEqual(code, 0, log)
        for f in ("raw.json", "view.json", "brief.json", "client_desk.html", "report.html", "report.txt", "push.txt"):
            self.assertTrue(os.path.exists(os.path.join(self.out(), f)), f)
        self.assertFalse(os.path.exists(os.path.join(self.out(), "email.txt")))
        self.assertIn("DRY RUN: nothing published", log)
        self.assertIn("WOULD PUSH: AGC Friday: Report ready", log)
        with open(os.path.join(self.out(), "push.txt")) as fh:
            push = fh.read()
        self.assertEqual(len(push.strip().splitlines()), 1)

    def test_monday(self):
        code, log = run_main(["--client", "agc", "--mode", "auto", "--now", fx.MONDAY.isoformat(), "--out-dir", self.out()])
        self.assertEqual(code, 0, log)
        self.assertIn("PUSH: AGC Monday:", log)
        with open(os.path.join(self.out(), "email.txt")) as fh:
            email = fh.read()
        self.assertTrue(email.startswith("Subject: Private and shared rooms this week"))
        self.assertFalse(os.path.exists(os.path.join(self.out(), "report.html")))

    def test_auto_mode(self):
        self.assertEqual(run.resolve_mode("auto", fx.MONDAY), "monday")
        self.assertEqual(run.resolve_mode("auto", fx.NOW), "friday")
        self.assertEqual(run.resolve_mode("auto", fx.NOW.replace(day=4)), "full")

    def test_brief_is_small_and_safe(self):
        run_main(["--client", "agc", "--mode", "full", "--now", fx.NOW.isoformat(), "--out-dir", self.out(), "--stage", "data"])
        with open(os.path.join(self.out(), "brief.json")) as fh:
            b = json.load(fh)
        self.assertLess(len(json.dumps(b)), 12000)
        self.assertEqual({c["verdict"] for c in b["callers"]}, {"family-likely", "not-a-family", "unclear"})
        self.assertNotRegex(json.dumps(b), r"\+?1?555\d{7}|@example")

    def test_notes_stage(self):
        out = self.out()
        run_main(["--client", "agc", "--mode", "full", "--now", fx.NOW.isoformat(), "--out-dir", out, "--stage", "data"])
        with open(os.path.join(out, "notes.json"), "w") as f:
            json.dump({"report_note": "The new room photos went up this week.",
                       "triage": {"u5": {"verdict": "robocall-likely", "reason": "same recorded silence as the wave"}}}, f)
        code, log = run_main(["--client", "agc", "--stage", "page", "--out-dir", out, "--dry-run"])
        self.assertEqual(code, 0, log)
        self.assertIn("triage override: Caller 5005 -> robocall-likely", log)
        with open(os.path.join(out, "view.json")) as fh:
            view = json.load(fh)
        u5 = next(i for i in view["triage"] if i["cid"] == "u5")
        self.assertEqual(u5["verdict"], "robocall-likely")
        self.assertIn("(checked by Claude)", u5["reason"])
        with open(os.path.join(out, "report.txt")) as a, open(os.path.join(out, "report.html")) as b:
            self.assertIn("The new room photos went up this week.", a.read() + b.read())

    def test_bad_note_is_left_out(self):
        out = self.out()
        run_main(["--client", "agc", "--mode", "friday", "--now", fx.NOW.isoformat(), "--out-dir", out, "--stage", "data"])
        with open(os.path.join(out, "notes.json"), "w") as f:
            json.dump({"report_note": "Our leads at the care home are up \u2014 great week."}, f)
        code, log = run_main(["--client", "agc", "--stage", "page", "--out-dir", out])
        self.assertEqual(code, 0)
        self.assertIn("report note HELD, left out", log)
        with open(os.path.join(out, "report.html")) as fh:
            self.assertNotIn("care home", fh.read())


class NoAccess(FakeGHL):
    drop = ("contacts",)

    def test_exit_2(self):
        code, log = run_main(["--client", "agc", "--mode", "friday", "--now", fx.NOW.isoformat(),
                              "--out-dir", os.path.join(self.tmp, "out")])
        self.assertEqual(code, 2)
        self.assertIn("NO ACCESS", log)


class ExportFallback(FakeGHL):
    drop = ("conversations__search",)

    def test_falls_back_to_export(self):
        raw = self.raw()
        self.assertEqual(raw["message_source"], "export (fallback)")
        self.assertEqual(len(raw["messages"]), len(fx.build()["messages"]))
        self.assertTrue(any(e[0] == "conversations" for e in raw["errors"]))


class Conversations(FakeGHL):
    def test_reads_conversations_and_skips_alert_contact(self):
        raw = self.raw()
        self.assertEqual(raw["message_source"], "conversations")
        self.assertFalse(any(m["cid"] == fx.ALERT for m in raw["messages"]))   # never read Joey's alert thread
        self.assertEqual(len(raw["messages"]), len(fx.build()["messages"]) - 30)
        self.assertEqual(raw["errors"], [])

    def test_email_thread_is_expanded(self):
        raw = self.raw()
        p6 = sorted((m["dir"], m.get("subj")) for m in raw["messages"] if m["cid"] == "p6" and m["type"] == "TYPE_EMAIL")
        self.assertEqual(p6, [("inbound", "Re: Discharges this week?"), ("outbound", "Discharges this week?")])


class Privacy(FakeGHL):
    def test_raw_has_no_phone_or_email(self):
        raw = self.raw()
        blob = json.dumps(raw)
        self.assertNotRegex(blob, r"\+1555\d{7}|\b555\d{7}\b")
        self.assertNotRegex(blob, r"[\w.+-]+@example\.(?:com|net|org)")
        u1 = next(c for c in raw["contacts"] if c["id"] == "u1")
        self.assertEqual(u1["phone"]["last4"], "0001")
        self.assertEqual(u1["phone"]["area"], "555")

    def test_internal_keys_from_users_and_location(self):
        raw = self.raw()
        self.assertEqual(len(raw["internal"]["phones"]), 3)           # user phone, user lcPhone, home line
        self.assertIn("samplegrove.example.com", raw["internal"]["domains"])
        self.assertIn("surven.ai", raw["internal"]["domains"])

    def test_mask(self):
        self.assertEqual(pull.mask("call 555-400-0006 or pat@example.com"), "call [number] or [email]")

    def test_real_name(self):
        self.assertTrue(pull.real_name("Pat", ""))
        for bad in ("", "Caller 1234", "+15551234567", "Unknown", "Wireless Caller"):
            self.assertFalse(pull.real_name(bad, ""), bad)


class Discovery(unittest.TestCase):
    def test_pick_by_name(self):
        pls = [{"id": "a", "name": "SVN | Family Leads"}, {"id": "b", "name": "Referral Partners"},
               {"id": "c", "name": "Hiring"}]
        self.assertEqual(pull.pick_by_name(pls, {"id": None, "match": ["family"]})[:2], ("a", "SVN | Family Leads"))
        self.assertEqual(pull.pick_by_name(pls, {"id": None, "match": ["referral partner", "partner"]})[0], "b")
        self.assertEqual(pull.pick_by_name(pls[2:], {"id": None, "match": ["family"], "fallback_id": "z"})[0], "z")
        self.assertEqual(pull.pick_by_name(pls[2:], {"id": None, "match": ["family"]})[0], None)
        cals = [{"id": "x", "name": "Old Tour", "isActive": False}, {"id": "y", "name": "Tour at Splendor Residence"}]
        self.assertEqual(pull.pick_by_name(cals, {"id": None, "match": ["tour"]})[0], "y")

    def test_splendor_profile(self):
        p = profile.load("splendor")
        self.assertIsNone(p["family_pipeline"]["id"])
        self.assertEqual(p["location"], "QxKf9rbHVJW6UvkFszds")
        self.assertIsNone(p["open_beds_email"])
        self.assertEqual(p["goal"]["tours"], 6)
        self.assertIn("FnhZ7GhOOdwMcjYM3VuZ", p["internal_contacts"])

    def test_export_retries_when_short(self):
        pages = [{"messages": [{"id": "1"}, {"id": "2"}], "nextCursor": "c", "total": 3},
                 {"messages": [], "total": 3},
                 {"messages": [{"id": "1"}, {"id": "2"}], "nextCursor": "c", "total": 3},
                 {"messages": [{"id": "3"}], "total": 3}]
        with mock.patch.object(pull.ghl, "call", side_effect=pages):
            got, err = pull.export_messages("L", "s", "e")
        self.assertIsNone(err)
        self.assertEqual(sorted(m["id"] for m in got), ["1", "2", "3"])


class ExportUnion(unittest.TestCase):
    def test_union_of_passes(self):
        passes = [([{"id": "1"}, {"id": "2"}], None), ([{"id": "1"}, {"id": "2"}, {"id": "3"}], None),
                  ([{"id": "3"}, {"id": "1"}], None)]
        with mock.patch.object(pull, "export_messages", side_effect=passes) as em:
            got, err, sizes = pull.export_union("L", "s", "e")
        self.assertEqual(sorted(m["id"] for m in got), ["1", "2", "3"])
        self.assertEqual(sizes, [2, 3, 2])
        self.assertEqual(em.call_count, 3)
        self.assertIsNone(err)

    def test_two_passes_when_nothing_new(self):
        same = ([{"id": "1"}], None)
        with mock.patch.object(pull, "export_messages", side_effect=[same, same, same]) as em:
            got, err, sizes = pull.export_union("L", "s", "e")
        self.assertEqual(em.call_count, 2)
        self.assertEqual(len(got), 1)


class Patch(unittest.TestCase):
    PATCH = os.path.join(TOOL, "proposals", "agc-collector-referral-partner.patch")
    SRC = "/home/user/morning-sales-brief/occupancy_os/collectors/agc.py"

    def test_patch_has_no_personal_data(self):
        with open(self.PATCH, encoding="utf-8") as fh:
            txt = fh.read()
        self.assertNotRegex(txt, r"\+1\d{10}|@gmail|@[\w-]+\.(com|net|org)")
        self.assertIn("def is_referral_partner(c):", txt)

    @unittest.skipUnless(os.path.exists(SRC) and shutil.which("patch"), "collector repo or patch tool not here")
    def test_patch_applies_and_excludes_partners(self):
        tmp = tempfile.mkdtemp(prefix="cd_patch_")
        try:
            os.makedirs(os.path.join(tmp, "occupancy_os", "collectors"))
            dst = os.path.join(tmp, "occupancy_os", "collectors", "agc.py")
            shutil.copy(self.SRC, dst)
            r = subprocess.run(["patch", "-p1", "-i", self.PATCH], cwd=tmp, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            code = (
                "import importlib.util, sys\n"
                "s = importlib.util.spec_from_file_location('agc', %r)\n"
                "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                "print(m.not_family_reason({'tags': ['referral-partner'], 'customFields': []}))\n"
                "print(m.not_family_reason({'tags': ['partner-hospital'], 'customFields': []}))\n"
                "print(m.not_family_reason({'tags': [], 'customFields': [{'id': m.F_STAGE, 'value': 'partner: talked'}]}))\n"
                "print(m.not_family_reason({'tags': ['referred-by-partner'], 'customFields': []}))\n" % dst)
            out = subprocess.run(["python3", "-I", "-c", code], capture_output=True, text=True, cwd=tmp)
            self.assertEqual(out.stdout.split(), ["referral_partner", "referral_partner", "referral_partner", "None"],
                             out.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RepoHygiene(unittest.TestCase):
    """The repo is public: nothing this tool ships may hold a phone number or an email address."""

    def test_no_personal_data_in_tool_files(self):
        roots = [TOOL, os.path.join(ROOT, ".claude", "skills", "client_desk")]
        files = [os.path.join(ROOT, "routines", "client_desk.md")]
        for r in roots:
            for dp, _, fs in os.walk(r):
                if "__pycache__" in dp:
                    continue
                files += [os.path.join(dp, f) for f in fs if f.endswith((".py", ".md", ".json", ".patch"))]
        # 555 numbers are fictional (tests only); anything else that looks like a US phone number fails
        phone = re.compile(r"(?<![\w.])\(?(?!555)[2-9]\d{2}\)?[\s.-]\d{3}[\s.-]\d{4}\b|\+1(?!555)\d{10}")
        mail = re.compile(r"\b[\w.+-]+@(?!example\.)[\w-]+\.(?:com|net|org|ai|co|us)\b")
        for f in files:
            if not os.path.exists(f):
                continue
            with open(f, encoding="utf-8") as fh:
                txt = fh.read()
            self.assertIsNone(phone.search(txt), "%s: %s" % (f, (phone.search(txt) or [""])[0]))
            self.assertIsNone(mail.search(txt), "%s: %s" % (f, (mail.search(txt) or [""])[0]))
