"""Shared setup: a temp GHL_FAKE_DIR with the synthetic fixtures, then a pull and the built numbers."""
import os
import shutil
import tempfile
import unittest

from tools.client_desk.tests import fixtures as fx


class FakeGHL(unittest.TestCase):
    drop = ()
    now = fx.NOW

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="client_desk_test_")
        self.fake = fx.write_fake_dir(os.path.join(self.tmp, "ghl"), drop=self.drop)
        self._old = os.environ.get("GHL_FAKE_DIR")
        os.environ["GHL_FAKE_DIR"] = self.fake

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GHL_FAKE_DIR", None)
        else:
            os.environ["GHL_FAKE_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def profile(self):
        from tools.client_desk import profile
        return profile.load("agc")

    def raw(self):
        from tools.client_desk import pull
        return pull.pull(self.profile(), now=self.now, workers=1)

    def built(self, mode="friday"):
        from tools.client_desk import metrics
        raw = self.raw()
        desk, cls = metrics.build(raw, self.profile(), self.now, mode)
        return raw, desk, cls

    def view(self, mode="friday"):
        from tools.client_desk import run
        return run.build_view(self.raw(), self.profile(), self.now, mode, dry_run=True)
