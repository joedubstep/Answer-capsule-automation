"""Shared setup: a temp GHL_FAKE_DIR with the synthetic fixtures, and a pulled + scored evidence object."""
import os
import shutil
import tempfile
import unittest

from tools.ls_evidence import profile as prof
from tools.ls_evidence.tests import fixtures as fx


class FakeGHL(unittest.TestCase):
    drop = ()
    patch = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ls_evidence_test_")
        self.fake = fx.write_fake_dir(os.path.join(self.tmp, "ghl"), drop=self.drop,
                                      patch=type(self).patch)
        self._old = os.environ.get("GHL_FAKE_DIR")
        os.environ["GHL_FAKE_DIR"] = self.fake
        self.settings = prof.load_settings()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GHL_FAKE_DIR", None)
        else:
            os.environ["GHL_FAKE_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self, **kw):
        from tools.ls_evidence import pull
        return pull.pull(fx.profile(), self.settings, now=kw.pop("now", fx.NOW), workers=2, **kw)

    def evidence(self, now=None, prev=None, entered_through=None, raw=None):
        from tools.ls_evidence import score
        return score.build(raw or self.raw(), self.settings, now=now or fx.NOW, prev=prev,
                           entered_through=entered_through)

    @staticmethod
    def leads(ev):
        return {r["first"]: r for r in ev["leads"]}

    @staticmethod
    def calls(ev, state="booked"):
        out = {}
        for r in ev["calls"]:
            if state is None or r["state"] == state:
                out[r["first"]] = r
        return out
