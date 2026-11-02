"""Shared setup: a temp GHL_FAKE_DIR with the synthetic fixtures, and a pulled + scored desk."""
import os
import shutil
import tempfile
import unittest

from tools.hq_desk.tests import fixtures as fx


class FakeGHL(unittest.TestCase):
    drop = ()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hq_desk_test_")
        self.fake = fx.write_fake_dir(os.path.join(self.tmp, "ghl"), drop=self.drop)
        self._old = os.environ.get("GHL_FAKE_DIR")
        os.environ["GHL_FAKE_DIR"] = self.fake

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GHL_FAKE_DIR", None)
        else:
            os.environ["GHL_FAKE_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def raw(self):
        from tools.hq_desk import pull
        return pull.pull(fx.profile(), now=fx.NOW, workers=2)

    def desk(self, routines=None):
        from tools.hq_desk import score
        return score.build(self.raw(), now=fx.NOW, routines=routines)

    @staticmethod
    def by_code(desk):
        return {l["code"] or l["first"]: l for l in desk["items"]}
