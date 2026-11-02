"""Unknown-caller triage: each synthetic caller gets the verdict Joey would give, with the reason."""
from tools.client_desk import triage as T
from tools.client_desk.tests.base import FakeGHL


class Verdicts(FakeGHL):
    def items(self):
        raw, _, cls = self.built()
        return {i["cid"]: i for i in T.triage(raw, cls, self.profile(), self.now)}

    def test_each_caller(self):
        it = self.items()
        want = {"u1": "robocall-likely", "u2n": "robocall-likely", "u3": "family-likely", "u4": "not-a-family",
                "u5": "unclear", "u6": "family-likely", "w0": "robocall-likely", "w1": "robocall-likely",
                "w2": "robocall-likely", "old1": "robocall-likely"}
        self.assertEqual({k: it[k]["verdict"] for k in want}, want)

    def test_reasons(self):
        it = self.items()
        self.assertIn("nobody spoke", it["u1"]["reason"])
        self.assertIn("Caller 0002", it["u1"]["reason"])                    # near-identical number
        self.assertIn("robocall wave", it["w1"]["reason"])
        self.assertIn("area code 444", it["w1"]["reason"])
        self.assertIn('talked about "looking for a place"', it["u3"]["reason"])
        self.assertIn("hiring", it["u4"]["reason"])
        self.assertIn("texted us", it["u6"]["reason"])
        self.assertEqual(it["u5"]["lean"], "robocall")
        self.assertIn("listen to the recording", it["u5"]["reason"])

    def test_older_flag_and_order(self):
        raw, _, cls = self.built()
        items = T.triage(raw, cls, self.profile(), self.now)
        self.assertTrue(next(i for i in items if i["cid"] == "old1")["older"])
        self.assertFalse(next(i for i in items if i["cid"] == "u1")["older"])
        self.assertEqual(items[-1]["cid"], "old1")                          # older ones go last
        self.assertIn(items[0]["verdict"], ("family-likely",))              # families first

    def test_only_last_four_digits(self):
        it = self.items()
        for i in it.values():
            self.assertRegex(i["label"], r"^Caller \d{4}$")
            blob = repr(i)
            self.assertNotRegex(blob, r"\d{7,}")                            # no full number anywhere
        self.assertEqual(it["u1"]["answer"], "Caller 0001: robocall")

    def test_answers_and_counts(self):
        raw, _, cls = self.built()
        items = T.triage(raw, cls, self.profile(), self.now)
        txt = T.answers_text(items).splitlines()
        u3 = next(i["label"] for i in items if i["cid"] == "u3")
        self.assertTrue(any(line.startswith(u3 + ": family (") for line in txt), txt)
        self.assertIn("Caller 0001: robocall", txt)                         # robocalls need no reason in the block
        c = T.counts(items)
        self.assertEqual(sum(c.values()), 10)
        self.assertEqual(c["family-likely"], 2)


class Words(FakeGHL):
    def test_greeting_is_not_the_caller(self):
        summ = {"status": "ok", "text": "1: Hey. | 1: This is Joy from Sample Grove Home. | 1: Hello? | 1: Hello?"}
        n, text = T.caller_words(summ, ["joey", "joy"], ["sample", "grove", "home"])
        self.assertEqual(n, 0)
        summ = {"status": "ok", "text": "1: Hey. | 2: I need a room for my father."}
        n, text = T.caller_words(summ, ["joey"], [])
        self.assertGreater(n, 4)
        self.assertIn("father", text)

    def test_no_transcript(self):
        self.assertEqual(T.caller_words({"status": "none", "text": ""}, ["joey"], []), (None, ""))
