"""The command line tool: exit codes, JSON shape, input sources and flags."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def run(args, stdin=None):
    p = subprocess.run([sys.executable, "-m", "tools.copy_check.check"] + args, cwd=ROOT, input=stdin,
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


class TestCLI(unittest.TestCase):
    def test_clean_text_exit_0(self):
        code, out, err = run(["--context", "prospect_sms", "--text", "Hi Pat, it's Joey. Did I miss you?"])
        self.assertEqual(code, 0, out + err)
        self.assertTrue(out.startswith("Copy check: PASS"))
        self.assertEqual(err, "")

    def test_block_exit_1_and_human_report(self):
        code, out, _ = run(["--context", "client", "--text", "Your care home is full."])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("Copy check: FIX FIRST"), out)
        self.assertIn("MUST FIX", out)
        self.assertIn("[care_home]", out)
        self.assertIn("Fix:", out)

    def test_warn_only_exit_0(self):
        code, out, _ = run(["--context", "prospect_email", "--text", "Great to meet you!"])
        self.assertEqual(code, 0)
        self.assertIn("LOOK AT", out)

    def test_json(self):
        code, out, _ = run(["--context", "prospect_email", "--text", "Thanks for the enquiry!", "--json"])
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertFalse(d["ok"])
        self.assertIn("grade", d)
        self.assertEqual({i["rule"] for i in d["issues"]}, {"british_spelling", "exclamation"})
        for i in d["issues"]:
            self.assertTrue({"rule", "severity", "match", "line", "fix"} <= set(i))

    def test_file_and_stdin(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hi Pat,\n\nWe send you more leads.\n")
            path = f.name
        try:
            code, out, _ = run(["--context", "prospect_email", "--file", path, "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["issues"][0]["line"], 3)
        finally:
            os.unlink(path)
        code, out, _ = run(["--context", "client", "--file", "-", "--json"], stdin="All good here.")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_flags(self):
        code, out, _ = run(["--context", "prospect_sms", "--text", "Hi Pat.", "--require-link", "--require-optout",
                            "--json"])
        self.assertEqual(code, 1)
        self.assertEqual([i["rule"] for i in json.loads(out)["issues"]], ["missing_link", "missing_optout"])
        code, _, _ = run(["--context", "prospect_sms", "--require-link", "--require-optout", "--text",
                          "Hi Pat. Pick a time: https://example.com/book Reply STOP to opt out."])
        self.assertEqual(code, 0)

    def test_template_flag(self):
        args = ["--context", "client", "--text", "Hi {{contact.first_name}}, see you soon."]
        self.assertEqual(run(args)[0], 1)
        self.assertEqual(run(args + ["--template"])[0], 0)

    def test_bad_arguments_exit_2(self):
        self.assertEqual(run(["--context", "family", "--text", "Hi."])[0], 2)
        self.assertEqual(run(["--context", "client"])[0], 2)
        self.assertEqual(run(["--context", "client", "--file", "/nonexistent/nope.txt"])[0], 2)

    def test_checker_error_is_exit_2_not_1(self):
        """Exit 1 means 'fix the copy'. A broken checker must never look like that."""
        code, out, err = run(["--context", "client", "--text", "Hi.", "--rules", "/nonexistent/rules.json"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("copy_check error", err)

    def test_windows_1252_and_bom_files(self):
        """A Word or Outlook export in cp1252 still shows its em dash (byte 0x97) to the checker."""
        with tempfile.TemporaryDirectory() as d:
            cp = os.path.join(d, "cp1252.txt")
            with open(cp, "wb") as f:
                f.write(b"Hi Pat \x97 it\x92s Joey.")
            code, out, _ = run(["--context", "prospect_email", "--file", cp, "--json"])
            self.assertEqual(code, 1)
            self.assertIn("dash", [i["rule"] for i in json.loads(out)["issues"]])
            bom = os.path.join(d, "bom.txt")
            with open(bom, "wb") as f:
                f.write(b"\xef\xbb\xbfHi Pat, it's Joey. Did I miss you?")
            code, out, _ = run(["--context", "prospect_sms", "--file", bom, "--json"])
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["issues"], [])
        p = subprocess.run([sys.executable, "-m", "tools.copy_check.check", "--context", "client", "--file", "-",
                            "--json"], cwd=ROOT, input=b"Your care home \x96 full.", capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 1)
        self.assertEqual({i["rule"] for i in json.loads(p.stdout)["issues"]}, {"care_home", "dash"})


if __name__ == "__main__":
    unittest.main()
