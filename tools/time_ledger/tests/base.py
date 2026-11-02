"""Shared test helpers: the synthetic page (same format as the real To-Do page, invented content) and a temp
work folder so nothing lands in /tmp/time_ledger."""
import json
import os
import shutil
import tempfile
import unittest

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
EDITED = "2026-11-02T14:30:00.000Z"          # 9:30 am Eastern on Nov 2


def page_md():
    with open(os.path.join(FIX, "page_synthetic.md"), encoding="utf-8") as f:
        return f.read()


def page_fetch_json():
    """The page wrapped the way the Notion fetch tool returns it."""
    return json.dumps({"metadata": {"type": "page"}, "title": "Sample To - Do", "text": page_md(),
                       "page_last_edited_at": EDITED})


def by(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


class TempWork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="time_ledger_test_")
        self._old = os.environ.get("TIME_LEDGER_DIR")
        os.environ["TIME_LEDGER_DIR"] = os.path.join(self.tmp, "work")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("TIME_LEDGER_DIR", None)
        else:
            os.environ["TIME_LEDGER_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p
