"""Fathom meeting list -> which recordings are new, and what kind of call each one is.

Inputs:
  --list     the text mcp__Fathom__list_meetings returned, saved as is. Each meeting is one line:
             "- <title> | <YYYY-MM-DD> | id: <recording id> | url: <url> | recorded by <name> | <invitees>"
             (a JSON list of meetings with the same fields also works).
  --library  /tmp/call_engine/library.json: the rows already in Notion, as
             {"sales": [{"Call": ..., "Link": ..., "createdTime": ...}], "ls": [...]}
             (the raw Notion SQL result {"results": [...]} also works for either key).
  --kinds    optional /tmp/call_engine/kinds.json: {"<recording id>": "discovery|close|follow-up|coaching|onboarding|other"}
             the model's decisions for meetings this file could not classify from the title.

Commands (from the repo root):
  python3 -m tools.call_engine.meetings new --list L --library LIB [--since YYYY-MM-DD] [--window-days 4]
        [--max 3] [--kinds K] [--today YYYY-MM-DD]
      prints JSON {"todo": [...], "need_kind": [...], "skipped": [...], "waiting": n, "cursor": "..."}
  python3 -m tools.call_engine.meetings prior --list L --name "Pat Example" [--email pat@example.com]
      prints earlier meetings with this person (for call prep)

Scheduled review: meetings inside the last --window-days (Eastern dates) that are not in a library yet. A call
whose review was held one night is tried again the next night, while it is inside the window. "cursor" (the newest
listed meeting already in a library) is reported only.
Backfill: --since a date, no window. Either way at most --max per run, oldest first; "waiting" says how many are left.

Library rows whose Link has no Fathom call id (share links like fathom.video/share/..., other note links, or no
link) cannot be matched by id. A meeting is treated as "probably already in the library" when such a row's Call
title carries the meeting's date (M/D or YYYY-MM-DD) and either the meeting is a coaching call and the row is in
the LS library, or the title shares a name with the row. Those go to "skipped" with the row title, never to todo.
"""
import argparse
import datetime as _dt
import json
import re
import sys

from shared import et

LINE = re.compile(r"^\s*-\s+(?P<title>.*?)\s+\|\s+(?P<date>\d{4}-\d{2}-\d{2})\s+\|\s+id:\s*(?P<id>\d+)\s+\|\s+url:\s*(?P<url>\S+)"
                  r"(?:\s+\|\s+recorded\s+by\s+(?P<rec>[^|]*?))?(?:\s+\|\s+(?P<inv>.*))?\s*$")
CALL_ID = re.compile(r"fathom\.video/calls/(\d+)")
SHARE = re.compile(r"fathom\.video/share/([A-Za-z0-9_-]+)")

# kind -> Sales Call Library "Type"
LIBRARY_TYPE = {"discovery": "Discovery", "close": "Close", "follow-up": "Follow-up"}
SALES_KINDS = set(LIBRARY_TYPE)
KINDS = SALES_KINDS | {"coaching", "onboarding", "other"}

# Title rules, checked in this order. Company domains (never personal emails) mark coaching groups.
COACH_DOMAINS = ("leadsuite.agency", "leadscape.au")
TITLE_RULES = [
    ("coaching", re.compile(r"\bmaster\s?mind\b|\bcoach(?:ing)?\b|\boffer\s+operators\b|\baccount\s+manager\b|"
                            r"\bgroup\s+call\b|\bstudents\b|\boffice\s+hours\b|\btraining\b", re.I)),
    ("onboarding", re.compile(r"\bon[\s-]?boarding\b|\bkick[\s-]?off\b|\bgo[\s-]?live\b|\bcheck[\s-]?in\b|\bday\s+(?:30|60|90)\b|"
                              r"\bjp\s+\d", re.I)),
    ("close", re.compile(r"\bclos(?:e|ing)\s+call\b|\bagreement\b|\bsign(?:ing)?\s+call\b|\bpt\.?\s?2\b|\bpart\s+2\b", re.I)),
    ("follow-up", re.compile(r"\bfollow[\s-]?up\b|\bcall\s?back\b|\bsecond\s+call\b|\bbamfam\b", re.I)),
    ("discovery", re.compile(r"\bdisco(?:very)?\b|\bstrategy\s+call\b|\bconsult(?:ation)?\b|\bsales\s+call\b|\bdemo\b|\bpt\.?\s?1\b|"
                             r"\bjoey\s*x\s+\w|\w+\s+x\s+joey\b|\bsurven\s*(?:&|x|and)\s+\w", re.I)),
    ("other", re.compile(r"\bproposal\b|\bvendor\b|\bpartnership\b|\binterview\b|\bpodcast\b|\bwfm\b|\bmarketing\s+strategy\b", re.I)),
    # weak coaching words come last: a Lead Suite ad lead's discovery call can carry "Lead Suite" in its title
    ("coaching", re.compile(r"\(ls\)|\blead\s?suite\b", re.I)),
]
# Titles that say nothing about the call: the model reads the Fathom summary and decides.
VAGUE = re.compile(r"^\s*impromptu\b|^\s*(?:joey|joseph)\b[\w .]*\s+and\s+\S|^\s*[\w.'-]+(?:\s+[\w.'-]+)?\s*$", re.I)


def parse_list(text):
    """Fathom list_meetings output (text lines or JSON) -> list of meeting dicts."""
    text = (text or "").strip()
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text)
        items = data.get("meetings", data.get("items", [])) if isinstance(data, dict) else data
        out = []
        for m in items:
            url = m.get("url") or m.get("share_url") or ""
            out.append(_norm({"title": m.get("title") or m.get("meeting_title") or "", "date": (m.get("date") or
                              m.get("created_at") or m.get("recording_start_time") or "")[:10],
                              "recording_id": str(m.get("recording_id") or m.get("id") or ""), "url": url,
                              "recorded_by": (m.get("recorded_by") or {}).get("name") if isinstance(m.get("recorded_by"), dict)
                              else m.get("recorded_by"),
                              "invitees": [i.get("email") or i.get("name") if isinstance(i, dict) else i
                                           for i in (m.get("calendar_invitees") or m.get("invitees") or [])]}))
        return out
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        inv = [x.strip() for x in (m.group("inv") or "").split(",") if x.strip()]
        out.append(_norm({"title": m.group("title").strip(), "date": m.group("date"), "recording_id": m.group("id"),
                          "url": m.group("url"), "recorded_by": (m.group("rec") or "").strip() or None, "invitees": inv}))
    return out


def _norm(m):
    cid = CALL_ID.search(m.get("url") or "")
    m["call_id"] = cid.group(1) if cid else None
    return m


def link_keys(link):
    """A Notion 'Link' value -> the keys it can match on (call id and/or share token and the bare url)."""
    keys = set()
    if not link:
        return keys
    c, s = CALL_ID.search(link), SHARE.search(link)
    if c:
        keys.add("call:" + c.group(1))
    if s:
        keys.add("share:" + s.group(1))
    keys.add("url:" + link.split("?")[0].rstrip("/"))
    return keys


def _rows(v):
    if isinstance(v, dict):
        return v.get("results") or v.get("rows") or []
    return v or []


def library_keys(library):
    keys = set()
    for k in ("sales", "ls"):
        for r in _rows(library.get(k)):
            keys |= link_keys(r.get("Link") or r.get("link") or "")
    return keys


MD_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")
ISO_DATE = re.compile(r"\b\d{4}-(\d{2})-(\d{2})\b")
_GENERIC = {"mastermind", "master", "mind", "call", "calls", "coaching", "group", "weekly", "offer", "operators",
            "review", "reviews", "joey", "joseph", "and", "the", "with", "discovery", "follow", "close", "meeting",
            "google", "meet", "impromptu", "surven", "sam", "lead", "suite", "zoom", "session"}


def _md(d):
    return "%d/%d" % (int(d[5:7]), int(d[8:10]))


def soft_rows(library):
    """Library rows that have no Fathom call id in Link: {lib, title, dates (M/D), tokens}."""
    out = []
    for lib in ("sales", "ls"):
        for r in _rows(library.get(lib)):
            link = r.get("Link") or r.get("link") or ""
            title = r.get("Call") or r.get("call") or ""
            if CALL_ID.search(link) or not title:
                continue
            dates = {"%d/%d" % (int(m), int(d)) for m, d in MD_DATE.findall(title)}
            dates |= {"%d/%d" % (int(m), int(d)) for m, d in ISO_DATE.findall(title)}
            if dates:
                out.append({"lib": lib, "title": title, "dates": dates,
                            "tokens": {t for t in re.findall(r"[a-z]{3,}", title.lower())} - _GENERIC})
    return out


def soft_match(m, kind, soft):
    """-> the library row title this meeting probably already has, or None."""
    if not m.get("date"):
        return None
    md = _md(m["date"])
    toks = {t for t in re.findall(r"[a-z]{3,}", (m.get("title") or "").lower())} - _GENERIC
    for r in soft:
        if md not in r["dates"]:
            continue
        if (kind == "coaching" and r["lib"] == "ls") or (toks & r["tokens"]):
            return r["title"]
    return None


def meeting_keys(m):
    keys = {"url:" + (m.get("url") or "").split("?")[0].rstrip("/")}
    if m.get("call_id"):
        keys.add("call:" + m["call_id"])
    return keys


def classify(m, kinds=None):
    """-> (kind or None, reason). None means the title is too vague: read the Fathom summary and decide."""
    rid = str(m.get("recording_id"))
    if kinds and rid in kinds:
        k = str(kinds[rid]).lower().strip()
        return (k if k in KINDS else "other"), "decided from the summary"
    inv = [str(i).lower() for i in (m.get("invitees") or [])]
    if any(i.endswith("@" + d) or i.endswith("." + d) for i in inv for d in COACH_DOMAINS):
        return "coaching", "coach group invitees"
    if len(inv) >= 5:
        return "coaching", "group call (%d invitees)" % len(inv)
    title = m.get("title") or ""
    for kind, rx in TITLE_RULES:
        if rx.search(title):
            return kind, "title"
    if VAGUE.search(title):
        return None, "vague title"
    return None, "no rule matched"


def select_new(meetings, library, since=None, window_days=4, max_n=3, kinds=None, today=None):
    today = today or et.now_et().date()
    done = library_keys(library)
    soft = soft_rows(library)
    processed = [m for m in meetings if meeting_keys(m) & done]
    cursor = max((m["date"] for m in processed), default=None)
    lo = since or (today - _dt.timedelta(days=window_days)).isoformat()
    cands = [m for m in meetings if m["date"] >= lo and not (meeting_keys(m) & done)]
    cands.sort(key=lambda m: (m["date"], int(m["recording_id"] or 0)))
    todo, need, skipped = [], [], []
    for m in cands:
        kind, why = classify(m, kinds)
        item = dict(m, kind=kind, why=why)
        dup = soft_match(m, kind, soft)
        if dup:
            item["why"] = "probably already in the library: %s" % dup
            skipped.append(item)
        elif kind is None:
            need.append(item)
        elif kind in SALES_KINDS or kind == "coaching":
            item["library"] = "sales" if kind in SALES_KINDS else "ls"
            item["type"] = LIBRARY_TYPE.get(kind, "Coaching")
            todo.append(item)
        else:
            skipped.append(item)
    waiting = max(0, len(todo) - max_n) if max_n else 0
    return {"cursor": cursor, "from": lo, "todo": todo[:max_n] if max_n else todo, "need_kind": need,
            "skipped": [{"recording_id": s["recording_id"], "date": s["date"], "kind": s["kind"], "why": s["why"]}
                        for s in skipped],
            "waiting": waiting, "already_in_library": len(processed)}


def _tokens(s):
    return {t for t in re.findall(r"[a-z]{3,}", (s or "").lower())} - {"joey", "joseph", "and", "call", "discovery",
                                                                        "meeting", "the", "with", "google", "meet",
                                                                        "impromptu", "surven"}


def prior(meetings, name=None, email=None, before=None):
    """Earlier recordings with this person, newest first. Each has "match": email (their address is an invitee),
    full name (first and last name in the title) or first name (only the first name; Joey's titles are usually
    "<First> discovery", so check the summary before you trust it)."""
    toks = [t for t in re.findall(r"[a-z]{3,}", (name or "").lower()) if t in _tokens(t)]
    first, last = (toks[0], toks[-1]) if toks else (None, None)
    out = []
    for m in meetings:
        if before and m["date"] >= before:
            continue
        tt = _tokens(m.get("title"))
        how = None
        if email and any(email.lower() == str(i).lower() for i in m.get("invitees") or []):
            how = "email"
        elif first and last and first != last and {first, last} <= tt:
            how = "full name"
        elif first and first in tt:
            how = "first name"
        if how:
            row = {k: m.get(k) for k in ("title", "date", "recording_id", "url")}
            row["match"] = how
            out.append(row)
    rank = {"email": 0, "full name": 0, "first name": 1}
    out.sort(key=lambda x: x["date"], reverse=True)
    out.sort(key=lambda x: rank[x["match"]])
    return out


def _load_json(path, default):
    if not path:
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tools.call_engine.meetings")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--list", required=True)
    n.add_argument("--library", required=True)
    n.add_argument("--since")
    n.add_argument("--window-days", type=int, default=4)
    n.add_argument("--max", type=int, default=3)
    n.add_argument("--kinds")
    n.add_argument("--today")
    p = sub.add_parser("prior")
    p.add_argument("--list", required=True)
    p.add_argument("--name")
    p.add_argument("--email")
    p.add_argument("--before")
    a = ap.parse_args(argv)
    meetings = parse_list(open(a.list, encoding="utf-8").read())
    if a.cmd == "new":
        today = _dt.date.fromisoformat(a.today) if a.today else None
        res = select_new(meetings, _load_json(a.library, {}), since=a.since, window_days=a.window_days, max_n=a.max,
                         kinds=_load_json(a.kinds, {}), today=today)
        res["listed"] = len(meetings)
        print(json.dumps(res, indent=1))
    else:
        print(json.dumps(prior(meetings, a.name, a.email, a.before), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
