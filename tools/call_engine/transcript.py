"""Parse a Fathom transcript into turns and compute the numbers a call review needs.

Input format (what mcp__Fathom__get_meeting_transcript returns, one turn per line):
    [MM:SS](https://fathom.video/calls/<id>?timestamp=<secs>) Speaker Name: what they said
Also accepted: [H:MM:SS](...) for long calls, and the short form "[MM:SS] Speaker: text" (no link), in which
case pass --url so each turn still gets a link. Lines that do not start with a timestamp continue the turn above.

Library:
    from tools.call_engine.transcript import analyze, parse
    a = analyze(text, host=None, base_url=None, call_date=None)

CLI (from the repo root):
    python3 -m tools.call_engine.transcript --file t.txt [--host "Joey g"] [--url <fathom call url>]
        [--date 2026-10-29] [--summary] [--out a.json]
--summary prints a short human-readable block (no quotes); default prints the full JSON.
Exit 0 ok, 2 no turns parsed.

Fathom's speaker labels sometimes drift by a line (the first words of a turn belong to the other person), so
every number here is evidence for the review, not a verdict.
"""
import argparse
import datetime as _dt
import json
import re
import sys

from tools.call_engine import rules

WPS = 2.5          # words per second, used only to size the very last turn
LINE = re.compile(r"^\s*\[(?P<ts>\d{1,2}(?::\d{2}){1,2})\](?:\((?P<url>[^)\s]+)\))?\s+(?P<spk>[^:\n]{1,80}?):(?:\s(?P<text>.*))?$")
WORD = re.compile(r"[A-Za-z0-9']+")
SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")

_FLAGS = [dict(f, _re=rules.compile_all(f["patterns"])) for f in rules.FLAGS]
_MOVES = [dict(m, _re=rules.compile_all(m["patterns"])) for m in rules.MOVES]
_OBJ = [dict(o, _re=rules.compile_all(o["patterns"])) for o in rules.OBJECTIONS]
_PROMISE = rules.compile_all(rules.PROMISE)
_PROMISE_X = re.compile(rules.PROMISE_EXCLUDE, re.I)
_MONEY = re.compile(rules.MONEY, re.I)
_PRICE_CTX = re.compile(rules.PRICE_CONTEXT, re.I)


# ---------------------------------------------------------------- parsing

def ts_to_secs(ts):
    parts = [int(p) for p in ts.split(":")]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


def fmt_ts(secs):
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def clean_base(url):
    if not url:
        return None
    return url.split("?")[0].split("#")[0]


def link_for(base, secs):
    return "%s?timestamp=%d" % (base, secs) if base else None


def unwrap(text):
    """A saved tool result can be JSON ({"result": "..."} or [{"type": "text", "text": "..."}]) instead of the
    plain transcript. Return the transcript text inside it, or the input unchanged."""
    t = (text or "").strip()
    if not t or t[0] not in "[{\"" or LINE.match(t.splitlines()[0]):
        return text
    try:
        data = json.loads(t)
    except ValueError:
        return text
    found = []

    def walk(v):
        if isinstance(v, str):
            if re.search(r"\[\d{1,2}:\d{2}", v):
                found.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(data)
    return "\n".join(found) if found else text


def parse(text, base_url=None):
    """Text -> list of turns {i, t, ts, url, speaker, text, words}."""
    base = clean_base(base_url)
    turns = []
    for raw in (unwrap(text) or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = LINE.match(line)
        if m:
            secs = ts_to_secs(m.group("ts"))
            url = m.group("url")
            if url and not base:
                base = clean_base(url)
            turns.append({"t": secs, "ts": fmt_ts(secs), "url": url or link_for(base, secs),
                          "speaker": m.group("spk").strip(), "text": (m.group("text") or "").strip()})
        elif turns:
            turns[-1]["text"] = (turns[-1]["text"] + " " + line.strip()).strip()
    for i, t in enumerate(turns):
        t["i"] = i
        t["words"] = len(WORD.findall(t["text"]))
        if not t["url"]:
            t["url"] = link_for(base, t["t"])
    for i, t in enumerate(turns):
        nxt = turns[i + 1]["t"] if i + 1 < len(turns) else None
        t["dur"] = max(0.0, float(nxt - t["t"])) if nxt is not None else t["words"] / WPS
    return turns


def find_host(turns, host=None):
    speakers = []
    for t in turns:
        if t["speaker"] not in speakers:
            speakers.append(t["speaker"])
    if host:
        for s in speakers:
            if s.lower() == host.lower():
                return s
        for s in speakers:
            if s.lower().startswith(host.lower()) or host.lower().startswith(s.lower()):
                return s
        return None
    for s in speakers:
        first = s.split()[0].lower() if s.split() else ""
        if first in rules.HOST_FIRST_NAMES:
            return s
    return None


def sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text or "") if s.strip()]


def _quote(s, n=300):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 3] + "..."


# ---------------------------------------------------------------- analysis

def _hit(turn, sentence):
    return {"t": turn["t"], "ts": turn["ts"], "url": turn["url"], "speaker": turn["speaker"], "quote": _quote(sentence)}


def talk_ratio(turns):
    words, secs = {}, {}
    for t in turns:
        words[t["speaker"]] = words.get(t["speaker"], 0) + t["words"]
        secs[t["speaker"]] = secs.get(t["speaker"], 0.0) + t["dur"]
    tw, ts_ = sum(words.values()) or 1, sum(secs.values()) or 1.0
    return {s: {"words": words[s], "pct_words": round(100.0 * words[s] / tw, 1),
                "seconds": int(round(secs[s])), "pct_time": round(100.0 * secs[s] / ts_, 1)} for s in words}


def monologues(turns, host):
    """Runs of consecutive host turns. Duration runs to the next turn by someone else (or the end)."""
    runs, cur = [], None
    for t in turns:
        if t["speaker"] == host:
            if cur is None:
                cur = {"start": t, "words": 0, "end_t": None}
            cur["words"] += t["words"]
            cur["last"] = t
        else:
            if cur is not None:
                cur["end_t"] = t["t"]
                runs.append(cur)
                cur = None
    if cur is not None:
        cur["end_t"] = cur["last"]["t"] + cur["last"]["dur"]
        runs.append(cur)
    out = []
    for r in runs:
        out.append({"t": r["start"]["t"], "ts": r["start"]["ts"], "url": r["start"]["url"],
                    "seconds": int(round(max(0, r["end_t"] - r["start"]["t"]))), "words": r["words"],
                    "opening": _quote(r["start"]["text"], 120)})
    return out


def _share(turns, host, start=None, end=None):
    hw = tw = 0
    for t in turns:
        if start is not None and t["t"] < start:
            continue
        if end is not None and t["t"] >= end:
            continue
        tw += t["words"]
        if t["speaker"] == host:
            hw += t["words"]
    return round(100.0 * hw / tw, 1) if tw else None


def scan_flags(turns, host):
    flags = []
    for t in turns:
        if t["speaker"] != host:
            continue
        for s in sentences(t["text"]):
            for f in _FLAGS:
                m = next((r.search(s) for r in f["_re"] if r.search(s)), None)
                if not m:
                    continue
                item = _hit(t, s)
                item.update({"rule": f["id"], "severity": f["severity"], "label": f["label"], "fix": f["fix"],
                             "match": m.group(0)})
                flags.append(item)
    flags.sort(key=lambda x: (rules.SEVERITY_ORDER.get(x["severity"], 9), x["t"]))
    return flags


_URGENT = re.compile(r"\bprice\w*\b|\bincrease\w*\b|\bdeadline\b|\bends?\b|\bgoes\s+up\b|\boriginal\b", re.I)
# "Nov 16", "November 16th", "Dec. 1" or "the 16th". A bare "the 2" ("the 2 beds") is not a date.
_DAYREF = re.compile(r"\b(?:(?:nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?|the\s+(\d{1,2})(?:st|nd|rd|th))\b",
                     re.I)


def scan_deadline(turns, host, deadline):
    """Joey names a deadline day that is not the one in config (the day itself or the day after is fine)."""
    if not deadline or not host:
        return []
    ok = {deadline.day, (deadline + _dt.timedelta(days=1)).day}
    out = []
    for t in turns:
        if t["speaker"] != host:
            continue
        for s in sentences(t["text"]):
            m = _DAYREF.search(s)
            day = int(m.group(1) or m.group(2)) if m else None
            if m and _URGENT.search(s) and day not in ok:
                item = _hit(t, s)
                item.update({"rule": "deadline_mismatch", "severity": "high", "match": m.group(0),
                             "label": "Deadline said on the call is not the real one",
                             "fix": "The deadline is %s (config/surven.json). Say that date." % deadline.strftime("%A %b %d").replace(" 0", " ")})
                out.append(item)
    return out


def scan_moves(turns, host):
    out = {}
    for mv in _MOVES:
        hits = []
        for t in turns:
            who = "host" if t["speaker"] == host else "guest"
            if mv["speaker"] != "any" and mv["speaker"] != who:
                continue
            for s in sentences(t["text"]):
                if any(r.search(s) for r in mv["_re"]):
                    hits.append(_hit(t, s))
                    break
        out[mv["id"]] = {"label": mv["label"], "count": len(hits), "first": hits[0] if hits else None,
                         "at": [h["ts"] for h in hits[:12]], "_hits": hits}
    return out


def first_price(turns, host):
    for t in turns:
        if t["speaker"] != host:
            continue
        for s in sentences(t["text"]):
            if not _MONEY.search(s) or not _PRICE_CTX.search(s):
                continue
            if s.rstrip().endswith("?") and re.search(r"\byou(?:r|\s+guys)?\b", s, re.I):
                continue     # restating their own rate back to them, not our price
            if re.search(r"\bclient\s+ad\s+spend\b", s, re.I):
                continue
            return _hit(t, s)
    return None


def scan_objections(turns, host):
    out = []
    for i, t in enumerate(turns):
        if t["speaker"] == host:
            continue
        for s in sentences(t["text"]):
            for o in _OBJ:
                if any(r.search(s) for r in o["_re"]):
                    reply = next((u for u in turns[i + 1:i + 4] if u["speaker"] == host), None)
                    item = _hit(t, s)
                    item.update({"kind": o["id"], "label": o["label"]})
                    if reply:
                        item["reply"] = {"ts": reply["ts"], "url": reply["url"], "quote": _quote(reply["text"], 200)}
                    out.append(item)
                    break
    return out


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def next_business_day(d):
    d = d + _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += _dt.timedelta(days=1)
    return d


def due_from(sentence, call_date):
    """A plain due date for an owed item from words in the promise. Default: next business day."""
    if not call_date:
        return None, "no call date"
    s = sentence.lower()
    if re.search(r"\b(?:today|tonight|this\s+(?:afternoon|evening)|end\s+of\s+(?:the\s+)?day|right\s+after)\b", s):
        return call_date, "said today"
    if re.search(r"\btomorrow\b", s):
        return call_date + _dt.timedelta(days=1), "said tomorrow"
    for i, wd in enumerate(_WEEKDAYS):
        if re.search(r"\b%s\b" % wd, s):
            delta = (i - call_date.weekday()) % 7 or 7
            return call_date + _dt.timedelta(days=delta), "said " + wd.capitalize()
    if re.search(r"\bnext\s+week\b", s):
        return call_date + _dt.timedelta(days=(7 - call_date.weekday()) or 7), "said next week"
    if re.search(r"\b(?:end\s+of\s+(?:the\s+)?week|this\s+week)\b", s):
        delta = (4 - call_date.weekday()) % 7
        return call_date + _dt.timedelta(days=delta), "said this week"
    return next_business_day(call_date), "default: next business day"


def scan_promises(turns, host, call_date=None):
    out = []
    for t in turns:
        if t["speaker"] != host:
            continue
        for s in sentences(t["text"]):
            if any(r.search(s) for r in _PROMISE) and not _PROMISE_X.search(s):
                due, why = due_from(s, call_date)
                item = _hit(t, s)
                item.update({"due": due.isoformat() if due else None, "due_why": why})
                out.append(item)
    return out


def _check(cid, label, result, evidence=None, note=""):
    return {"id": cid, "label": label, "result": result, "evidence": evidence, "note": note}


def auto_checks(a):
    """Deterministic first pass on the rubric rows Python can see. The model confirms or overrides."""
    mv, out = a["moves"], []
    gt = [f for f in a["flags"] if f["rule"] == "good_time_ask"]
    r_min = a["rapport_minutes"]
    if gt:
        res, note = "miss", "asked about a good time"
    elif r_min is None:
        res, note = "partial", "no clear first question found"
    elif 2 <= r_min <= 5:
        res, note = "pass", "first question at %.1f min" % r_min
    else:
        res, note = "partial", "first question at %.1f min (aim for 2 to 5)" % r_min
    out.append(_check("S1", "Open", res, gt[0] if gt else (mv["discovery_open"]["first"] or mv["agenda"]["first"]), note))
    pitch = a["pitch_start"]
    for cid, mid, before_pitch in (("S3", "timeline", False), ("S4", "tried", False), ("S5", "cost", False),
                                   ("S7", "goal", False), ("S8", "capacity", True), ("S10", "decision_maker", True)):
        m = mv[mid]
        if not m["count"]:
            out.append(_check(cid, m["label"], "miss", None, "not found in your lines"))
        elif before_pitch and pitch and m["first"]["t"] > pitch["t"]:
            out.append(_check(cid, m["label"], "partial", m["first"], "only after the pitch started (%s)" % pitch["ts"]))
        else:
            out.append(_check(cid, m["label"], "pass", m["first"], "%d time(s)" % m["count"]))
    com = mv["commitment"]["first"]
    if com and (pitch is None or com["t"] <= pitch["t"]):
        out.append(_check("S9", "Commitment before the pitch", "pass", com, ""))
    elif com:
        out.append(_check("S9", "Commitment before the pitch", "partial", com, "asked after the pitch started"))
    else:
        out.append(_check("S9", "Commitment before the pitch", "miss", None, "no commitment question found"))
    tie, anyq = mv["tie_down"]["count"], mv["any_questions"]["count"]
    out.append(_check("S11", "Tie-downs, not 'any questions'", "pass" if anyq <= 2 else "partial",
                      mv["any_questions"]["first"], "%d tie-down(s), %d 'any questions'" % (tie, anyq)))
    fp = a["first_price"]
    if fp is None:
        out.append(_check("S12", "Price after commitment", "n/a", None, "no price said"))
    elif com and com["t"] < fp["t"] and mv["timeline"]["count"]:
        out.append(_check("S12", "Price after commitment", "pass", fp, "price at %s" % fp["ts"]))
    else:
        out.append(_check("S12", "Price after commitment", "miss", fp, "price at %s before a timeline and a yes to change"
                          % fp["ts"]))
    after = (lambda h: pitch is None or h["t"] >= pitch["t"])      # an ask before the pitch is just the frame
    asks = [h for k in ("deposit", "payment_close") for h in mv[k]["_hits"] if after(h)]
    closed = bool(asks)
    nxt = mv["next_step"]["count"]
    res = "pass" if (closed and nxt) else ("partial" if (closed or nxt) else "miss")
    out.append(_check("S15", "Close or deposit asked, next call booked", res,
                      (min(asks, key=lambda h: h["t"]) if asks else None) or mv["next_step"]["first"],
                      "deposit/payment asked: %s, next call proposed: %s" % ("yes" if closed else "no", "yes" if nxt else "no")))
    lm = a["host_longest_monologue"]
    disc = a["host_share_before_pitch"]
    after = a["host_share_after_price"]
    bad = []
    if lm and lm["seconds"] > 150:
        bad.append("longest stretch %ds" % lm["seconds"])
    if disc is not None and disc > 60:
        bad.append("you had %s%% of the words before the pitch" % disc)
    if after is not None and after > 70:
        bad.append("you had %s%% of the words after the price" % after)
    out.append(_check("J1", "Talk less, stop after the ask", "miss" if len(bad) >= 2 else ("partial" if bad else "pass"),
                      lm, "; ".join(bad) or "ok"))
    return out


def analyze(text, host=None, base_url=None, call_date=None, deadline=None):
    turns = parse(text, base_url)
    if isinstance(call_date, str) and call_date:
        call_date = _dt.date.fromisoformat(call_date[:10])
    if isinstance(deadline, str) and deadline:
        deadline = _dt.date.fromisoformat(deadline[:10])
    out = {"turns": len(turns)}
    if not turns:
        out["error"] = "no turns parsed"
        return out
    h = find_host(turns, host)
    speakers = []
    for t in turns:
        if t["speaker"] not in speakers:
            speakers.append(t["speaker"])
    end = turns[-1]["t"] + turns[-1]["dur"]
    out.update({"host": h, "speakers": speakers, "duration_s": int(round(end)), "duration": fmt_ts(end),
                "talk_ratio": talk_ratio(turns), "base_url": clean_base(turns[0]["url"]) if turns[0]["url"] else None})
    if h is None:
        out["warning"] = "host speaker not found; pass --host with Joey's speaker label"
    mons = monologues(turns, h) if h else []
    out["host_longest_monologue"] = max(mons, key=lambda m: (m["seconds"], m["words"])) if mons else None
    out["host_monologues_over_90s"] = [m for m in mons if m["seconds"] > 90]
    host_turns = [t for t in turns if t["speaker"] == h]
    out["host_questions"] = sum(1 for t in host_turns for s in sentences(t["text"]) if s.endswith("?"))
    hw, hs = sum(t["words"] for t in host_turns), sum(t["dur"] for t in host_turns)
    out["host_words_per_minute"] = int(round(60.0 * hw / hs)) if hs > 0 else None
    out["flags"] = scan_flags(turns, h) + scan_deadline(turns, h, deadline)
    out["flags"].sort(key=lambda x: (rules.SEVERITY_ORDER.get(x["severity"], 9), x["t"]))
    out["moves"] = scan_moves(turns, h)
    out["first_price"] = first_price(turns, h) if h else None
    out["first_price_ask"] = out["moves"]["price_ask"]["first"]
    starts = [x for x in (out["moves"]["screen_share"]["first"], out["first_price"]) if x]
    out["pitch_start"] = min(starts, key=lambda x: x["t"]) if starts else None
    firsts = [out["moves"][k]["first"] for k in ("discovery_open", "empty_beds", "problem_probe", "timeline")
              if out["moves"][k]["first"]]
    out["rapport_minutes"] = round(min(x["t"] for x in firsts) / 60.0, 1) if firsts else None
    out["host_share_before_pitch"] = _share(turns, h, end=out["pitch_start"]["t"]) if (h and out["pitch_start"]) else (
        _share(turns, h) if h else None)
    out["host_share_after_price"] = _share(turns, h, start=out["first_price"]["t"]) if (h and out["first_price"]) else None
    out["promises"] = scan_promises(turns, h, call_date) if h else []
    out["objection_candidates"] = scan_objections(turns, h) if h else []
    out["auto_checks"] = auto_checks(out)
    for v in out["moves"].values():
        v.pop("_hits", None)
    out["note"] = "Speaker labels come from Fathom and can be off by a line. Listen before acting on a flag."
    return out


def summary(a):
    """Short human-readable block with numbers only (no quotes), for smoke tests and logs."""
    if a.get("error"):
        return "transcript: " + a["error"]
    h = a["host"]
    lines = ["turns %d, length %s, speakers %d, host %s" % (a["turns"], a["duration"], len(a["speakers"]), h or "NOT FOUND")]
    others = [s for s in a["speakers"] if s != h]
    for s, v in sorted(a["talk_ratio"].items(), key=lambda kv: -kv[1]["words"]):
        who = "host" if s == h else "other %d" % (others.index(s) + 1)
        lines.append("  %s: %s%% of words, %s%% of time" % (who, v["pct_words"], v["pct_time"]))
    lm = a["host_longest_monologue"]
    if lm:
        lines.append("longest host monologue: %ds (%d words) at %s" % (lm["seconds"], lm["words"], lm["ts"]))
    lines.append("host questions: %d, host pace: %s words/min" % (a["host_questions"], a["host_words_per_minute"]))
    lines.append("first price (host): %s; prospect asked about price: %s" % (
        a["first_price"]["ts"] if a["first_price"] else "none",
        a["first_price_ask"]["ts"] if a["first_price_ask"] else "no"))
    lines.append("host share of words before pitch: %s%%, after price: %s%%" % (a["host_share_before_pitch"],
                                                                              a["host_share_after_price"]))
    by = {}
    for f in a["flags"]:
        by.setdefault((f["severity"], f["rule"]), []).append(f["ts"])
    lines.append("flags: %d" % len(a["flags"]))
    for (sev, rid), tss in sorted(by.items(), key=lambda kv: (rules.SEVERITY_ORDER.get(kv[0][0], 9), kv[0][1])):
        lines.append("  [%s] %s at %s" % (sev, rid, ", ".join(tss[:8])))
    found = [k for k, v in a["moves"].items() if v["count"]]
    lines.append("moves found: " + ", ".join("%s@%s" % (k, a["moves"][k]["first"]["ts"]) for k in found))
    lines.append("promises: %d, objection candidates: %d" % (len(a["promises"]), len(a["objection_candidates"])))
    lines.append("auto checks: " + ", ".join("%s=%s" % (c["id"], c["result"]) for c in a["auto_checks"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tools.call_engine.transcript")
    ap.add_argument("--file", required=True, help="transcript text file ('-' for stdin)")
    ap.add_argument("--host", help="Joey's speaker label, e.g. 'Joey g' (auto-detected if left out)")
    ap.add_argument("--url", help="the Fathom call URL, used to build links when lines have none")
    ap.add_argument("--date", help="call date YYYY-MM-DD, for owed-item due dates")
    ap.add_argument("--deadline", help="price-raise deadline YYYY-MM-DD (from config) to check what Joey says")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--out", help="also write the JSON here")
    a = ap.parse_args(argv)
    text = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    res = analyze(text, host=a.host, base_url=a.url, call_date=a.date, deadline=a.deadline)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
    print(summary(res) if a.summary else json.dumps(res, indent=1))
    return 0 if res.get("turns") else 2


if __name__ == "__main__":
    sys.exit(main())
