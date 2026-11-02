"""Call review: transcript -> evidence packet -> (model scorecard) -> Notion row + Gmail draft payloads.

Files live in /tmp/call_engine/<recording id>/ (or under $CALL_ENGINE_DIR). Commands (from the repo root):

  packet  --rid ID --transcript T [--new new.json | --meeting meeting.json] [--host "Joey g"]
          Runs transcript.py, adds the rubric rows and the meeting facts. Writes packet.json and prints a compact
          view for the model: numbers, flags with quotes and links, auto checks, promises, objection candidates.
  render  --rid ID [--to prospect@email] [--dry-run]
          Reads packet.json and the model's review.json. Validates it, then writes:
            sales call:    row.json (Sales Call Library row: properties + page body), email.txt, draft.json
            coaching call: ls_row.json (LS Call Library row with the 5 takeaways)
          The follow-up email must pass the copy checker as prospect_email. Exit 1 lists what to fix.
  lookup  --name "First Last" | --email x@y
          Read-only Surven HQ GoHighLevel contact search (Surven HQ environment only): up to 5 matches with
          name, company and email, so the follow-up draft has an address.
  finish  [--dry-run]
          Reads every */result.json, prints the one-line final message, writes sms.txt when there is news.

review.json (written by the model), sales call:
  {"type": "Discovery|Close|Follow-up", "with": "Pat (Maple House)", "outcome": "one line",
   "scores": {"Q1": {"result": "pass|partial|miss|n/a", "note": "...", "ts": "12:01"}, ... every RUBRIC_ITEMS id},
   "flags_review": {"<flag number from the packet>": {"status": "confirmed|cleared", "why": "..."}},
   "extra_flags": [{"rule": "<a rules.FLAGS id>", "ts": "MM:SS", "quote": "exact words"}],
   "objections": [{"ts": "MM:SS", "objection": "...", "handling": "...", "verdict": "handled|partial|missed"}],
   "owed": [{"item": "...", "due": "YYYY-MM-DD", "ts": "MM:SS"}],
   "next_step": {"what": "...", "when": "YYYY-MM-DD HH:MM or null"},
   "fix_next_time": ["...", "...", "..."], "did_well": ["..."],
   "listen_for": [{"ts": "MM:SS", "label": "..."}],
   "email": {"to": "address or empty", "subject": "...", "body": "...", "reply_to_message_id": "optional"},
   "skip_email": "optional reason (e.g. Joey already followed up in Gmail on 10/30)"}
review.json, coaching call:
  {"kind": "coaching", "with": "...", "takeaways": [5 short lines], "listen_for": [{"ts": "MM:SS", "label": "..."}]}
"""
import argparse
import datetime as _dt
import glob
import json
import os
import re
import sys

from shared import et
from tools.call_engine import rules
from tools.call_engine import transcript as tr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.environ.get("CALL_ENGINE_DIR", "/tmp/call_engine")
DASHES = re.compile(r"[\u2012\u2013\u2014\u2015]")
TS_RX = re.compile(r"^\d{1,2}(?::\d{2}){1,2}$")
ITEM_IDS = [i for i, _ in rules.RUBRIC_ITEMS]
EMAIL_MAX_WORDS = 150
VIEW_MAX = 15          # lines per list in the packet view, so a long call stays cheap to read
PROP_MAX = 1900


def load_config():
    with open(os.path.join(ROOT, "config", "surven.json"), encoding="utf-8") as f:
        return json.load(f)


def rdir(rid):
    return os.path.join(WORK, str(rid))


def _read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)


def _clean(s):
    s = DASHES.sub(", ", str(s or "")).replace("<", "&lt;")
    return " ".join(s.split())


def md_date(iso):
    d = _dt.date.fromisoformat(iso[:10])
    return "%s %d/%d" % (d.strftime("%a"), d.month, d.day)


# ---------------------------------------------------------------- packet

def meeting_meta(rid, new_doc=None, meeting=None):
    if meeting:
        return meeting
    for m in ((new_doc or {}).get("todo") or []) + ((new_doc or {}).get("need_kind") or []):
        if str(m.get("recording_id")) == str(rid):
            return m
    return {"recording_id": str(rid), "_missing": True}


def build_packet(rid, text, meta, host=None, today=None):
    deadline = ((load_config().get("campaign") or {}).get("price_raise_deadline_et") or "")[:10] or None
    a = tr.analyze(text, host=host, base_url=meta.get("url"), call_date=meta.get("date"), deadline=deadline)
    today = today or et.now_et().date()
    age = None
    if meta.get("date"):
        age = (today - _dt.date.fromisoformat(meta["date"][:10])).days
    flags = []
    for n, f in enumerate(a.get("flags") or [], 1):
        flags.append(dict(f, n=n))
    return {"recording_id": str(rid), "meeting": meta, "days_since_call": age, "deadline": deadline, "analysis": a,
            "flags": flags,
            "rubric": [{"id": i, "label": l} for i, l in rules.RUBRIC_ITEMS],
            "auto": {c["id"]: c for c in a.get("auto_checks") or []}}


def packet_view(p):
    """What the model reads: compact, with quotes and links where it has to judge."""
    a = p["analysis"]
    lines = [tr.summary(a), "", "MEETING: %s | %s | %s | kind %s, %s days ago | price-raise deadline in config: %s" % (
        p["meeting"].get("title"), p["meeting"].get("date"), p["meeting"].get("url"), p["meeting"].get("kind"),
        p["days_since_call"], p.get("deadline"))]
    if p["meeting"].get("_missing"):
        lines.append("WARNING: this recording is not in new.json, so the date and link are unknown. Write meeting.json "
                     "(see the skill) and run packet again with --meeting.")
    lines.append("")
    lines.append("FLAGS (confirm or clear each in flags_review):")
    shown = [f for f in p["flags"] if f["severity"] == "high"]
    rest = [f for f in p["flags"] if f["severity"] != "high"]
    for f in shown + rest[:VIEW_MAX]:
        lines.append('  #%d [%s] %s at %s %s: "%s"' % (f["n"], f["severity"], f["rule"], f["ts"], f["url"], f["quote"]))
    if len(rest) > VIEW_MAX:
        lines.append("  (%d more medium or low flags in packet.json; they go on the page as listed)" % (len(rest) - VIEW_MAX))
    lines.append("")
    lines.append("AUTO CHECKS (confirm or override in scores):")
    for c in a.get("auto_checks") or []:
        ev = c.get("evidence") or {}
        lines.append("  %s %s: %s (%s)%s" % (c["id"], c["label"], c["result"], c["note"],
                                            ' at %s "%s"' % (ev.get("ts"), (ev.get("quote") or ev.get("opening") or "")[:120])
                                            if ev else ""))
    lines.append("")
    lines.append("PROMISES Joey made (owed-item candidates, default due dates):")
    for pr in (a.get("promises") or [])[:VIEW_MAX]:
        lines.append('  %s due %s (%s): "%s"' % (pr["ts"], pr["due"], pr["due_why"], pr["quote"][:160]))
    lines.append("")
    lines.append("OBJECTION CANDIDATES (their words, then Joey's next line):")
    for o in (a.get("objection_candidates") or [])[:VIEW_MAX]:
        rep = o.get("reply") or {}
        lines.append('  %s [%s] "%s" -> %s "%s"' % (o["ts"], o["kind"], o["quote"][:140], rep.get("ts", "-"),
                                                    rep.get("quote", "")[:120]))
    lines.append("")
    lines.append("SCORE THESE ROWS: " + ", ".join(ITEM_IDS))
    return "\n".join(lines)


# ---------------------------------------------------------------- validate + render

def _ts_ok(ts):
    return isinstance(ts, str) and bool(TS_RX.match(ts.strip()))


def _link(base, ts):
    return tr.link_for(base, tr.ts_to_secs(ts)) if base and _ts_ok(ts) else None


def validate_sales(rv, packet):
    errs = []
    if rv.get("type") not in ("Discovery", "Close", "Follow-up"):
        errs.append("type must be Discovery, Close or Follow-up")
    if not rv.get("with"):
        errs.append("with is empty")
    scores = rv.get("scores") or {}
    for i in ITEM_IDS:
        s = scores.get(i)
        if not s or s.get("result") not in rules.RESULTS:
            errs.append("scores.%s needs result pass|partial|miss|n/a" % i)
    flag_ids = [r["id"] for r in rules.FLAGS]
    for x in rv.get("extra_flags") or []:
        if not _ts_ok(x.get("ts")) or not x.get("quote"):
            errs.append("extra_flags items need ts MM:SS and the exact quote")
        if x.get("rule") not in flag_ids:
            errs.append("extra_flags rule must be one of: " + ", ".join(flag_ids))
    fx = rv.get("fix_next_time") or []
    if not 1 <= len(fx) <= 3:
        errs.append("fix_next_time needs 1 to 3 items")
    for o in rv.get("owed") or []:
        try:
            _dt.date.fromisoformat(str(o.get("due"))[:10])
        except ValueError:
            errs.append("owed item '%s' needs due YYYY-MM-DD" % (o.get("item") or "")[:40])
        if not o.get("item"):
            errs.append("owed item without text")
    for lf in rv.get("listen_for") or []:
        if not _ts_ok(lf.get("ts")):
            errs.append("listen_for ts must be MM:SS: %s" % lf.get("ts"))
    if not rv.get("listen_for"):
        errs.append("listen_for is empty (add the 3 to 6 moments worth a listen)")
    ns = rv.get("next_step") or {}
    if not ns.get("what"):
        errs.append("next_step.what is empty (say 'none booked' if none)")
    if not rv.get("skip_email"):
        em = rv.get("email") or {}
        if not em.get("subject") or not em.get("body"):
            errs.append("email.subject and email.body are needed (or set skip_email with the reason)")
    return errs


def check_email(subject, body):
    """Copy check the follow-up as prospect_email plus the house limits. -> (blocking list, warnings list)."""
    block, warn = [], []
    text = "%s\n\n%s" % (subject or "", body or "")
    try:
        from tools.copy_check.check import check
        r = check(text, "prospect_email")
        for i in r["issues"]:
            (block if i["severity"] == "block" else warn).append("%s: %s (fix: %s)" % (i["rule"], i["match"], i["fix"]))
    except Exception as e:  # noqa: BLE001
        warn.append("copy checker unavailable (%s); ran the house checks only" % type(e).__name__)
        if DASHES.search(text):
            block.append("dash: em or en dash")
    words = len(re.findall(r"[A-Za-z0-9']+", body or ""))
    if words > EMAIL_MAX_WORDS:
        block.append("length: %d words, keep it under %d" % (words, EMAIL_MAX_WORDS))
    last = [l.strip() for l in (body or "").strip().splitlines() if l.strip()]
    if not last or last[-1] != "Joey":
        block.append("sign-off: end with a line that says only 'Joey'")
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body or ""):
        warn.append("email address inside the body")
    return block, warn


def _authored_issues(texts):
    try:
        from tools.copy_check.check import check
    except Exception:  # noqa: BLE001
        return [], []
    block, warn = [], []
    for t in texts:
        if t:
            for i in check(DASHES.sub(", ", t), "internal")["issues"]:
                (block if i["severity"] == "block" else warn).append("%s: %s" % (i["rule"], i["match"] or t[:40]))
    return block, warn


def _flag_lines(packet, rv, base):
    fr = rv.get("flags_review") or {}
    confirmed, cleared = [], []
    for f in packet["flags"]:
        st = (fr.get(str(f["n"])) or {}).get("status")
        row = dict(f)
        row["why"] = (fr.get(str(f["n"])) or {}).get("why")
        (cleared if st == "cleared" else confirmed).append(row)
    for x in rv.get("extra_flags") or []:
        rule = next(r for r in rules.FLAGS if r["id"] == x.get("rule"))
        confirmed.append({"rule": rule["id"], "severity": rule["severity"], "label": rule["label"], "fix": rule["fix"],
                          "ts": x["ts"], "url": _link(base, x["ts"]), "quote": x["quote"], "t": tr.ts_to_secs(x["ts"])})
    confirmed.sort(key=lambda f: (rules.SEVERITY_ORDER.get(f["severity"], 9), f.get("t", 0)))
    return confirmed, cleared


WORD = {"pass": "Pass", "partial": "Partial", "miss": "Miss", "n/a": "N/A"}


def render_sales(packet, rv, now=None):
    a, meta = packet["analysis"], packet["meeting"]
    base = a.get("base_url") or (meta.get("url") or "").split("?")[0]
    url = meta.get("url") or base
    confirmed, cleared = _flag_lines(packet, rv, base)
    parts = []
    sc = rv["scores"]
    passed = sum(1 for i in ITEM_IDS if sc[i]["result"] == "pass")
    scored = sum(1 for i in ITEM_IDS if sc[i]["result"] != "n/a")
    parts.append("<b>OUTCOME:</b> %s" % _clean(rv.get("outcome") or ""))
    q = ["- %s %s. %s" % (dict(rules.RUBRIC_ITEMS)[i], WORD[sc[i]["result"]], _clean(sc[i].get("note")))
         for i in ("Q1", "Q2", "Q3")]
    parts.append("<b>THE 3 QUESTIONS</b>\n\n" + "\n".join(q))
    rows = []
    for i, label in rules.RUBRIC_ITEMS:
        if i in ("Q1", "Q2", "Q3"):
            continue
        s = sc[i]
        ts = s.get("ts")
        at = " ([%s](%s))" % (ts, _link(base, ts)) if _ts_ok(ts) and base else ""
        rows.append("- %s: %s. %s%s" % (label, WORD[s["result"]], _clean(s.get("note")), at))
    parts.append("<b>SCORECARD</b> (%d of %d passed)\n\n%s" % (passed, scored, "\n".join(rows)))
    tr_ = a.get("talk_ratio") or {}
    host = a.get("host")
    hw = tr_.get(host, {}).get("pct_words") if host else None
    lm = a.get("host_longest_monologue")
    fp, fa = a.get("first_price"), a.get("first_price_ask")
    nums = ["- You had %s%% of the words (%s%% before the pitch)." % (hw, a.get("host_share_before_pitch")),
            "- Longest stretch: %ds at [%s](%s)." % (lm["seconds"], lm["ts"], lm["url"]) if lm else "- Longest stretch: none.",
            "- Questions you asked: %d. Pace: %s words a minute." % (a.get("host_questions", 0), a.get("host_words_per_minute")),
            "- First price: %s. They asked about price: %s." % (
                "[%s](%s)" % (fp["ts"], fp["url"]) if fp else "never said",
                "[%s](%s)" % (fa["ts"], fa["url"]) if fa else "no"),
            "- Length: %s." % a.get("duration")]
    parts.append("<b>NUMBERS</b>\n\n" + "\n".join(nums))
    if confirmed:
        parts.append("<b>FLAGS</b>\n\n" + "\n".join('- [%s](%s) %s: "%s" %s' % (
            f["ts"], f["url"], f["label"], _clean(f["quote"])[:200], f["fix"]) for f in confirmed[:10]))
    obj = rv.get("objections") or []
    parts.append("<b>OBJECTIONS</b>\n\n" + ("\n".join("- [%s](%s) %s You: %s Verdict: %s." % (
        o.get("ts"), _link(base, o.get("ts")), _clean(o.get("objection")), _clean(o.get("handling")), o.get("verdict"))
        for o in obj) if obj else "- None raised."))
    owed = rv.get("owed") or []
    parts.append("<b>YOU OWE</b>\n\n" + ("\n".join("- [ ] %s. Due %s.%s" % (
        _clean(o["item"]).rstrip("."), md_date(o["due"]), " ([%s](%s))" % (o["ts"], _link(base, o["ts"])) if _ts_ok(o.get("ts")) else "")
        for o in owed) if owed else "- Nothing promised."))
    ns = rv.get("next_step") or {}
    parts.append("<b>NEXT STEP</b>\n\n- %s%s" % (_clean(ns.get("what")), " (%s)" % ns["when"] if ns.get("when") else ""))
    parts.append("<b>FIX NEXT TIME</b>\n\n" + "\n".join("%d. %s" % (i + 1, _clean(x)) for i, x in enumerate(rv["fix_next_time"])))
    if rv.get("did_well"):
        parts.append("<b>DID WELL</b>\n\n" + "\n".join("- " + _clean(x) for x in rv["did_well"][:3]))
    parts.append("<b>LISTEN FOR</b>\n\n" + "\n".join("- [%s](%s) %s" % (l["ts"], _link(base, l["ts"]), _clean(l.get("label")))
                                                    for l in rv["listen_for"]))
    notes = ["Speaker labels come from Fathom and can be off by a line. Listen before you act on a flag.",
             "Rubric: tools/call_engine/rubric.md in the Answer-capsule-automation repo."]
    for f in cleared:
        notes.append('Cleared flag at %s (%s): %s' % (f["ts"], f["rule"], _clean(f.get("why"))))
    built = et.to_et(now or et.now_utc()).strftime("%Y-%m-%d %I:%M %p ET")
    notes.append("Built by call_engine %s. Watched stays unchecked until you watch it." % built)
    parts.append("<toggle>\nNotes on this review\n\n%s\n</toggle>" % "\n".join("- " + n for n in notes))
    content = "\n\n".join(parts) + "\n"

    d = _dt.date.fromisoformat(meta["date"][:10]) if meta.get("date") else et.now_et().date()
    listen = " · ".join("%s %s" % (l["ts"], _clean(l.get("label"))) for l in rv["listen_for"])
    owed_txt = "; ".join("%s (due %s)" % (_clean(o["item"]), md_date(o["due"])) for o in owed) or "nothing owed"
    note = "%s Next: %s. Owe: %s. Score %d of %d." % (_clean(rv.get("outcome")), _clean(ns.get("what")), owed_txt, passed,
                                                      scored)
    cfg = load_config()
    ds = cfg["notion"]["sales_call_library_ds"].replace("collection://", "")
    props = {"Call": "%s %s %d/%d" % (_clean(rv["with"]), rv["type"], d.month, d.day), "Type": rv["type"],
             "With": _clean(rv["with"]), "Link": url, "Listen for": listen[:PROP_MAX], "notes": note[:PROP_MAX],
             "Watched": "__NO__", "Transcript": ("In Fathom: %s (open it, Transcript tab)" % url)[:PROP_MAX]}
    authored = [rv.get("outcome"), ns.get("what")] + list(rv.get("fix_next_time") or []) + list(rv.get("did_well") or [])
    authored += [o.get("handling") for o in obj] + [o.get("item") for o in owed]
    return {"parent": {"data_source_id": ds}, "properties": props, "content": content}, authored


def render_coaching(packet, rv):
    a, meta = packet["analysis"], packet["meeting"]
    base = a.get("base_url") or (meta.get("url") or "").split("?")[0]
    url = meta.get("url") or base
    errs = []
    tk = rv.get("takeaways") or []
    if len(tk) != 5:
        errs.append("takeaways needs exactly 5 lines")
    for t in tk:
        if len(re.findall(r"[A-Za-z0-9']+", t or "")) > 30:
            errs.append("takeaway over 30 words: %s" % (t or "")[:50])
    for lf in rv.get("listen_for") or []:
        if not _ts_ok(lf.get("ts")):
            errs.append("listen_for ts must be MM:SS")
    if errs:
        return None, errs, tk
    d = _dt.date.fromisoformat(meta["date"][:10]) if meta.get("date") else et.now_et().date()
    lf = rv.get("listen_for") or []
    content = "<b>5 TAKEAWAYS</b>\n\n" + "\n".join("%d. %s" % (i + 1, _clean(t)) for i, t in enumerate(tk))
    if lf:
        content += "\n\n<b>LISTEN FOR</b>\n\n" + "\n".join("- [%s](%s) %s" % (l["ts"], _link(base, l["ts"]), _clean(l.get("label")))
                                                          for l in lf)
    content += "\n\n<toggle>\nNotes\n\n- Added by call_engine from the Fathom transcript. Watched stays unchecked.\n</toggle>\n"
    cfg = load_config()
    ds = cfg["notion"]["ls_call_library_ds"].replace("collection://", "")
    title = re.sub(r"\s+", " ", meta.get("title") or "Coaching call").strip()
    props = {"Call": "%s %d/%d" % (_clean(title), d.month, d.day), "Type": "Coaching", "With": _clean(rv.get("with") or ""),
             "Link": url, "Listen for": " · ".join("%s %s" % (l["ts"], _clean(l.get("label"))) for l in lf)[:PROP_MAX],
             "notes": ("Takeaways: " + " | ".join(_clean(t) for t in tk))[:PROP_MAX], "Watched": "__NO__"}
    return {"parent": {"data_source_id": ds}, "properties": props, "content": content}, [], tk


def render(rid, to=None, dry_run=False, now=None):
    d = rdir(rid)
    packet = _read_json(os.path.join(d, "packet.json"))
    rv = _read_json(os.path.join(d, "review.json"))
    if packet is None or rv is None:
        return 2, ["packet.json or review.json missing in %s" % d], []
    kind = (rv.get("kind") or packet["meeting"].get("kind") or "").lower()
    result = {"recording_id": str(rid), "date": packet["meeting"].get("date"), "dry_run": dry_run}
    if kind == "coaching":
        row, errs, tk = render_coaching(packet, rv)
        if errs:
            return 1, errs, []
        ab, aw = _authored_issues(tk)
        if ab:
            return 1, ["copy (internal): " + x for x in ab], aw
        _write_json(os.path.join(d, "ls_row.json"), row)
        result.update({"kind": "coaching", "with": rv.get("with"), "row": "ls_row.json"})
        _write_json(os.path.join(d, "result.json"), result)
        return 0, [], aw
    errs = validate_sales(rv, packet)
    if errs:
        return 1, errs, []
    row, authored = render_sales(packet, rv, now)
    ab, aw = _authored_issues(authored)
    if ab:
        return 1, ["copy (internal page text): " + x for x in ab], aw
    warns = list(aw)
    em = rv.get("email") or {}
    draft = None
    if not rv.get("skip_email"):
        block, ewarn = check_email(em.get("subject"), em.get("body"))
        if block:
            return 1, ["email: " + b for b in block], ewarn
        warns += ["email: " + w for w in ewarn]
        addr = to or em.get("to") or ""
        draft = {"to": [addr] if addr else [], "subject": em["subject"].strip(), "body": em["body"].strip() + "\n",
                 "warnings": ewarn}
        if em.get("reply_to_message_id"):
            draft["replyToMessageId"] = em["reply_to_message_id"]
        if not addr:
            warns.append("email: no address found; the draft has no recipient")
        with open(os.path.join(d, "email.txt"), "w", encoding="utf-8") as f:
            f.write("Subject: %s\n\n%s" % (draft["subject"], draft["body"]))
        _write_json(os.path.join(d, "draft.json"), draft)
    _write_json(os.path.join(d, "row.json"), row)
    owed = rv.get("owed") or []
    first = re.split(r"[\s(]", rv.get("with") or "?")[0]
    result.update({"kind": "sales", "type": rv["type"], "with": rv.get("with"), "first": first,
                   "owed": [{"item": o["item"], "due": o["due"]} for o in owed], "draft": bool(draft),
                   "skip_email": rv.get("skip_email"), "row": "row.json",
                   "next_step": (rv.get("next_step") or {}).get("what")})
    _write_json(os.path.join(d, "result.json"), result)
    return 0, [], warns


def _tail(results, new_doc):
    """' Held: ...; N more waiting' for the final line, from new.json (todo that never rendered, and waiting)."""
    new_doc = new_doc or {}
    done = {str(r.get("recording_id")) for r in results}
    held = [m for m in new_doc.get("todo") or [] if str(m.get("recording_id")) not in done]
    out = ""
    if held:
        out += " Held, not written: %s." % ", ".join("%s %s" % (m.get("date"), (m.get("title") or "")[:40]) for m in held)
    if new_doc.get("waiting"):
        out += " %d more waiting; say \"run it again\"." % new_doc["waiting"]
    return out


def finish(dry_run=False, created=None, new_doc=None):
    results = []
    for p in sorted(glob.glob(os.path.join(WORK, "*", "result.json"))):
        results.append(_read_json(p))
    created = created or {}
    sales = [r for r in results if r.get("kind") == "sales"]
    coach = [r for r in results if r.get("kind") == "coaching"]
    tail = _tail(results, new_doc)
    if not results:
        return ("Call Review: nothing new." + tail) if not tail else ("Call Review: 0 calls reviewed." + tail), None
    def one(r):
        bits = ["%s %s" % (r.get("first"), r.get("type"))]
        if r.get("owed"):
            bits.append("you owe " + ", ".join("%s by %s" % (o["item"], md_date(o["due"])) for o in r["owed"][:3]))
        return ": ".join([bits[0], "; ".join(bits[1:])]) if len(bits) > 1 else bits[0]
    drafts = sum(1 for r in sales if r.get("draft"))
    if dry_run:
        line = "Call Review: dry run, nothing written. Would add %d sales row(s), %d Gmail draft(s), %d coaching row(s). %s" % (
            len(sales), drafts, len(coach), " | ".join(one(r) for r in sales))
        return (line.strip() + tail), None
    rows = sum(1 for r in results if created.get(r["recording_id"], {}).get("row"))
    made_drafts = sum(1 for r in sales if created.get(r["recording_id"], {}).get("draft"))
    line = "Call Review: %d sales call(s) reviewed, %d row(s) added, %d follow-up draft(s) in Gmail, %d coaching takeaway(s). %s" % (
        len(sales), rows, made_drafts, len(coach), " | ".join(one(r) for r in sales))
    line = line.strip() + tail
    sms = None
    done = [r for r in sales if created.get(r["recording_id"], {}).get("row")]
    if done:
        sms = "Call review ready (Notion, Sales Call Library). " + " | ".join(one(r) for r in done)
        if made_drafts:
            sms += ". Follow-up draft%s in Gmail." % ("s" if made_drafts > 1 else "")
    return line.strip(), sms


# ---------------------------------------------------------------- lookup

def lookup(name=None, email=None, cfg=None, limit=5):
    """Read-only Surven HQ GoHighLevel contact search by name or email. -> {"status", "contacts": [...]}.
    Only works in the Surven HQ environment; elsewhere status says so."""
    from shared import ghl
    cfg = cfg or load_config()
    loc = cfg["ghl"]["hq"]["location"]
    if not ghl.check_access(loc):
        return {"status": "Surven HQ GoHighLevel is not readable from this environment", "contacts": []}
    q = (email or name or "").strip()
    if len(q) < 3:
        return {"status": "give a name or email of 3 or more characters", "contacts": []}
    r = ghl.call("/contacts/", {"locationId": loc, "query": q, "limit": limit})
    if not ghl.ok(r):
        return {"status": "search failed (%s)" % r.get("error"), "contacts": []}
    out = []
    for c in (r.get("contacts") or [])[:limit]:
        out.append({"id": c.get("id"), "name": " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x),
                    "company": c.get("companyName"), "email": c.get("email"), "added": (c.get("dateAdded") or "")[:10],
                    "tags": (c.get("tags") or [])[:5]})
    return {"status": "ok", "contacts": out}


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tools.call_engine.review")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("packet")
    p.add_argument("--rid", required=True)
    p.add_argument("--transcript", required=True)
    p.add_argument("--new", default=os.path.join(WORK, "new.json"))
    p.add_argument("--meeting", help="meeting JSON {title, date, url, recording_id, kind, type} (on-demand runs)")
    p.add_argument("--host")
    r = sub.add_parser("render")
    r.add_argument("--rid", required=True)
    r.add_argument("--to")
    r.add_argument("--dry-run", action="store_true")
    lk = sub.add_parser("lookup", help="find the prospect's email in Surven HQ GoHighLevel (read-only)")
    lk.add_argument("--name")
    lk.add_argument("--email")
    f = sub.add_parser("finish")
    f.add_argument("--dry-run", action="store_true")
    f.add_argument("--created", default=os.path.join(WORK, "created.json"))
    f.add_argument("--new", default=os.path.join(WORK, "new.json"))
    f.add_argument("--sms", default=os.path.join(WORK, "sms.txt"))
    a = ap.parse_args(argv)
    if a.cmd == "packet":
        meta = meeting_meta(a.rid, _read_json(a.new, {}), _read_json(a.meeting) if a.meeting else None)
        with open(a.transcript, encoding="utf-8") as fh:
            text = fh.read()
        pk = build_packet(a.rid, text, meta, a.host)
        if not pk["analysis"].get("turns"):
            print("NO TURNS: the transcript file did not parse. Keep the [MM:SS] Speaker: text lines.")
            return 2
        _write_json(os.path.join(rdir(a.rid), "packet.json"), pk)
        print(packet_view(pk))
        print("\nWrote %s. Now write %s." % (os.path.join(rdir(a.rid), "packet.json"), os.path.join(rdir(a.rid), "review.json")))
        return 0
    if a.cmd == "render":
        code, errs, warns = render(a.rid, a.to, a.dry_run)
        for e in errs:
            print("must fix: " + e)
        for w in warns:
            print("look at: " + w)
        if code == 0:
            res = _read_json(os.path.join(rdir(a.rid), "result.json"))
            print("OK %s: %s" % (res.get("kind"), ", ".join(sorted(x for x in ("row.json", "ls_row.json", "draft.json")
                                                                 if os.path.exists(os.path.join(rdir(a.rid), x))))))
        return code
    if a.cmd == "lookup":
        print(json.dumps(lookup(a.name, a.email), indent=1))
        return 0
    if a.cmd == "finish":
        created = _read_json(a.created, {})
        line, sms = finish(a.dry_run, created, _read_json(a.new, {}))
        if sms:
            with open(a.sms, "w", encoding="utf-8") as fh:
                fh.write(sms)
        elif os.path.exists(a.sms):
            os.remove(a.sms)
        print(line)
        print("TEXT: " + a.sms if sms else "NO TEXT")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
