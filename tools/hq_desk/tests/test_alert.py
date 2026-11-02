import os
import tempfile

from tools.hq_desk import alert, render, drafts
from tools.hq_desk.tests.base import FakeGHL


class AlertTest(FakeGHL):
    URL = "https://claude.ai/artifact/example"

    def prev_page(self, desk):
        path = os.path.join(self.tmp, "prev.html")
        with open(path, "w") as f:
            f.write(render.render(desk))
        return path

    def test_first_run_texts(self):
        msg, why = alert.decide(self.desk(), None, self.URL)
        self.assertTrue(msg.startswith("Desk: 1 new hot: 41 Pat."))
        self.assertIn("Red: 1 lead wrote in and got no answer for over 24 hours.", msg)
        self.assertTrue(msg.endswith(self.URL))
        self.assertLessEqual(len(msg), alert.MAX_CHARS)

    def test_same_state_no_text(self):
        desk = self.desk()
        prev = alert.read_prev_state(self.prev_page(desk))
        msg, why = alert.decide(self.desk(), prev, self.URL)
        self.assertEqual(msg, "")
        self.assertEqual(why, "nothing new and urgent")

    def test_new_owed_draft_texts(self):
        prev = alert.read_prev_state(self.prev_page(self.desk()))
        desk = self.desk()
        sam = next(l for l in desk["items"] if l["code"] == "12")
        os.environ.pop("HQ_DESK_COPY_CHECK", None)
        desk, _, _ = drafts.merge(desk, {sam["id"]: {"owed": [{"for": 0, "kind": "email", "text": "Here is the Loom."}]}})
        msg, _ = alert.decide(desk, prev, "")
        self.assertEqual(msg, "Desk: 1 owed item drafted: 12 Sam.")

    def test_unmatched_owed_draft_is_not_news(self):
        prev = alert.read_prev_state(self.prev_page(self.desk()))
        desk = self.desk()
        sam = next(l for l in desk["items"] if l["code"] == "12")
        os.environ.pop("HQ_DESK_COPY_CHECK", None)
        desk, _, _ = drafts.merge(desk, {sam["id"]: {"owed": [{"for": 9, "kind": "email", "text": "Here it is."}]}})
        msg, why = alert.decide(desk, prev, "")
        self.assertEqual(msg, "")

    def test_hidden_hot_is_not_news(self):
        desk = self.desk()
        hot = next(l for l in desk["items"] if l["code"] == "41")
        hot["drafts"] = {"hide": "auto reply"}
        prev = {"hot": [], "owed_drafted": [], "red": ["unanswered"]}
        msg, why = alert.decide(desk, prev, "")
        self.assertEqual(msg, "")

    def test_missing_or_bad_prev(self):
        self.assertIsNone(alert.read_prev_state(None))
        bad = os.path.join(self.tmp, "bad.html")
        with open(bad, "w") as f:
            f.write("<p>no state</p>")
        self.assertIsNone(alert.read_prev_state(bad))
