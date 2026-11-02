"""Merge the model's drafts into the desk and run every draft through the copy checker.

  python3 -m tools.hq_desk.drafts [--drafts /tmp/hq_desk/drafts.json] [--desk /tmp/hq_desk/desk.json]

drafts.json (written by the model, keyed by the lead "id" from brief.json):
  {"<id>": {"sms": "text", "email_subject": "subject", "email": "body",
            "action": "optional better next step", "note": "optional one line for Joey",
            "hide": "optional reason this lead should not be on the desk today",
            "owed": [{"for": "<owed item text or its index>", "kind": "email|sms|note", "subject": "",
                      "text": "the deliverable", "sources": ["https://..."], "missing": "what only Joey has",
                      "done": "optional: why it looks done already (then no text)"}]}}

Every sms is checked as prospect_sms, every email (subject + body) and owed email as prospect_email, an owed
"note" (words for Joey, not the lead) as internal. The checker is tools/copy_check (BUILD-SPEC rule 4). Until
it exists, a basic built-in check of the hardest rules runs instead and the page says so. On top of the
checker, any draft with a phone number or an email address is held: the page never shows either.
An owed draft whose "for" matches no owed item of that lead is dropped and reported (it would never show).
Merging replaces every lead's drafts, so running it again after a fix is safe.
Exit 0 when nothing is held, 1 when any draft has a blocking issue (fix drafts.json and run again).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from tools.hq_desk import profile as prof
from tools.hq_desk.pull import write_json
from tools.hq_desk.score import EMAIL_RX, PHONE_RX, apply_hides

CHECKER = os.path.join(prof.REPO, "tools", "copy_check", "check.py")

BLOCK_RULES = [
    ("no dashes", r"[\u2013\u2014]", "Use a period or comma, never an em or en dash."),
    ("no emojis", "[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF]", "Take the emoji out."),
    ("no stop language", r"reply stop|text stop|unsubscribe|opt[ -]?out|we will not (email|text) you again",
     "Never write stop or opt-out language."),
    ("banned words", r"\bcare home\b|\benquiry\b", "Say assisted living home or home, and inquiry."),
    ("residents not patients", r"\bpatients?\b", "Say residents."),
    ("bad opener", r"is now a bad time", "Never ask if now is a bad time."),
]
WARN_RULES = [
    ("cold outreach words", r"\b(audit|assessment|grade|score)\b", "Avoid audit, assessment, grade and score."),
    ("no statistics", r"\d+(\.\d+)?\s?%", "No statistics in prospect copy."),
    ("price", r"\$\s?\d", "No price before a call unless they already heard it on one."),
    ("buzzwords", r"\b(leverage|unlock|journey|seamless|robust|game-?changer|circle back|dial in|double down)\b",
     "Use plain words."),
    ("got it", r"\bgot it\b", "Say Okay."),
    ("families not leads", r"\bleads?\b", "Say families."),
]


def basic_check(text, context):
    issues = []
    for rule, rx, fix in BLOCK_RULES:
        m = re.search(rx, text, re.I)
        if m and not (context == "internal" and rule in ("banned words", "residents not patients")):
            issues.append({"rule": rule, "severity": "block", "match": m.group(0), "fix": fix})
    if context != "internal":
        for rule, rx, fix in WARN_RULES:
            m = re.search(rx, text, re.I)
            if m:
                issues.append({"rule": rule, "severity": "warn", "match": m.group(0), "fix": fix})
        if text.count("?") > 1:
            issues.append({"rule": "one ask", "severity": "warn", "match": "?", "fix": "One question only."})
        if context == "prospect_sms" and len(text) > 160:
            issues.append({"rule": "sms length", "severity": "warn", "match": str(len(text)),
                           "fix": "Keep a text under 160 characters."})
        if context == "prospect_email" and len(text.split()) > 90:
            issues.append({"rule": "email length", "severity": "warn", "match": str(len(text.split())),
                           "fix": "Keep an email under about 80 words."})
    blocked = any(i["severity"] == "block" for i in issues)
    return {"status": "blocked" if blocked else ("warn" if issues else "ok"), "issues": issues, "checker": "basic"}


def _library():
    """The copy checker's own check(text, context), or None when tools/copy_check is not in this checkout."""
    if not os.path.exists(CHECKER):
        return None
    try:
        from tools.copy_check.check import check
        return check
    except Exception:  # noqa: BLE001  a broken checker must not stop the desk; basic checks run instead
        return None


def checker_cmd():
    """Which checker runs: a test override script, the copy checker, or None (basic checks)."""
    alt = os.environ.get("HQ_DESK_COPY_CHECK")
    if alt:
        return [sys.executable, alt]
    if _library():
        return [sys.executable, "-m", "tools.copy_check.check"]
    return None


def _result(out, blocked):
    issues = [{k: i.get(k) for k in ("rule", "severity", "match", "line", "message", "fix")}
              for i in out.get("issues") or []]
    return {"status": "blocked" if blocked else ("warn" if issues else "ok"), "issues": issues, "checker": "copy_check"}


def _failed(text, context, why):
    res = basic_check(text, context)
    res["issues"].append({"rule": "copy checker error", "severity": "warn", "match": "",
                          "fix": "The copy checker did not answer (" + why + "). Basic checks ran instead."})
    res["status"] = "blocked" if res["status"] == "blocked" else "warn"
    return res


def copy_check(text, context):
    """{"status": ok|warn|blocked, "issues": [...], "checker": "copy_check"|"basic"}

    Same contract as `python3 -m tools.copy_check.check --context <ctx> --file <path> --json`: ok is False
    when any issue blocks. Uses the checker's library when present (no subprocess per draft)."""
    alt = os.environ.get("HQ_DESK_COPY_CHECK")
    if not alt:
        fn = _library()
        if fn is None:
            return basic_check(text, context)
        try:
            out = fn(text, context)
        except Exception as e:  # noqa: BLE001
            return _failed(text, context, type(e).__name__)
        return _result(out, not out.get("ok"))
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        p = subprocess.run([sys.executable, alt, "--context", context, "--file", path, "--json"],
                           capture_output=True, text=True, cwd=prof.REPO, timeout=60)
    finally:
        os.unlink(path)
    try:
        out = json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError:
        out = {}
    if "ok" not in out:
        return _failed(text, context, "exit %s" % p.returncode)
    return _result(out, p.returncode != 0 or not out.get("ok"))


def contact_check(chk, text):
    """Hold a draft that carries a phone number or an email address (the page never shows either)."""
    m = EMAIL_RX.search(text) or PHONE_RX.search(text)
    if not m:
        return chk
    chk = dict(chk, issues=list(chk.get("issues") or []))
    chk["issues"].append({"rule": "no phone or email", "severity": "block", "match": "phone or email",
                          "fix": "Take out the phone number or email address. Use the source link instead."})
    chk["status"] = "blocked"
    return chk


def checked(text, context):
    return contact_check(copy_check(text, context), text)


def owed_index(lead, want):
    """The brief's index i of the due owed item a draft is "for" (an int, a digit string, or the item text)."""
    due = [x for x in lead.get("owed") or [] if x.get("due")]
    w = str(want).strip() if want is not None else ""
    if w.isdigit() and int(w) < len(due):
        return int(w)
    for i, x in enumerate(due):
        if w and w == str(x.get("text") or "").strip():
            return i
    return None


def _s(v):
    if isinstance(v, dict):
        v = v.get("text")
    return str(v).strip() if v not in (None, "") else ""


def merge(desk, drafts):
    """Returns (desk, report lines, held count)."""
    by_id = {l["id"]: l for l in desk.get("items", [])}
    for l in desk.get("items", []):
        l["drafts"] = {}              # a rerun after a fix starts clean
    report, held = [], 0
    for lid, d in (drafts or {}).items():
        if lid.startswith("_"):
            continue
        l = by_id.get(lid)
        if not l or not isinstance(d, dict):
            report.append(f"skip {lid}: not a lead on the desk")
            continue
        who = l.get("code") or l.get("first") or lid[:6]
        out = {}
        for k in ("action", "note", "hide"):
            if _s(d.get(k)):
                out[k] = _s(d.get(k))
        sms = _s(d.get("sms"))
        if sms:
            out["sms"] = {"text": sms, "check": checked(sms, "prospect_sms")}
        body = _s(d.get("email"))
        if body:
            ed = d.get("email")
            subj = _s(d.get("email_subject")) or (str(ed.get("subject") or "").strip() if isinstance(ed, dict) else "")
            full = (subj + "\n\n" + body) if subj else body
            out["email"] = {"subject": subj, "text": body, "check": checked(full, "prospect_email")}
        owed = []
        for o in d.get("owed") or []:
            if not isinstance(o, dict):
                continue
            kind = (o.get("kind") or "email").lower()
            idx = owed_index(l, o.get("for"))
            if idx is None:
                report.append(f"skip {who} owed for={o.get('for')!r}: no owed item with that i")
                continue
            row = {"for": idx, "kind": kind, "subject": _s(o.get("subject")), "text": _s(o.get("text")),
                   "sources": [str(u) for u in o.get("sources") or []], "missing": _s(o.get("missing")),
                   "done": _s(o.get("done"))}
            if row["text"]:
                ctx = {"sms": "prospect_sms", "note": "internal", "internal": "internal"}.get(kind, "prospect_email")
                full = (row["subject"] + "\n\n" + row["text"]) if row["subject"] else row["text"]
                row["check"] = checked(full, ctx)
            owed.append(row)
        if owed:
            out["owed"] = owed
        l["drafts"] = out
        for name, chk in [("text", (out.get("sms") or {}).get("check")), ("email", (out.get("email") or {}).get("check"))] + \
                         [(f"owed for={o['for']}", o.get("check")) for o in owed]:
            if not chk:
                continue
            if chk["status"] == "blocked":
                held += 1
                rules = "; ".join(f"{i.get('rule')}: {i.get('match')}" for i in chk["issues"]
                                  if i.get("severity", "block") != "warn")
                report.append(f"HELD {who} {name}: {rules}")
            elif chk["status"] == "warn":
                report.append(f"warn {who} {name}: " + "; ".join(str(i.get("rule")) for i in chk["issues"]))
    apply_hides(desk)
    return desk, report, held


def main(argv=None):
    ap = argparse.ArgumentParser(description="Merge and copy-check the model's drafts.")
    ap.add_argument("--drafts", default=os.path.join(prof.OUT_DIR, "drafts.json"))
    ap.add_argument("--desk", default=os.path.join(prof.OUT_DIR, "desk.json"))
    a = ap.parse_args(argv)
    with open(a.desk, encoding="utf-8") as f:
        desk = json.load(f)
    if not os.path.exists(a.drafts):
        print("drafts: none written")
        return 0
    with open(a.drafts, encoding="utf-8") as f:
        drafts = json.load(f)
    if not isinstance(drafts, dict):
        print("drafts: drafts.json must be one JSON object keyed by lead id")
        return 1
    desk, report, held = merge(desk, drafts)
    write_json(a.desk, desk)
    which = "copy_check" if checker_cmd() else "basic check (copy_check not installed yet)"
    n = sum(1 for k in drafts if not k.startswith("_"))
    print(f"drafts: {n} leads merged, checked with {which}, {held} held")
    for line in report:
        print("  " + line)
    return 1 if held else 0


if __name__ == "__main__":
    sys.exit(main())
