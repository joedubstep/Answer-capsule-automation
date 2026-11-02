"""Parse the 15-minute log on Joey's To-Do page into one row per action.

  python3 -m tools.time_ledger.parse --page /tmp/time_ledger/page.md [--edited 2026-11-02T16:08:12Z] [--out rows.json]

Input is the page as the Notion fetch tool returns it (the JSON result, or just its Notion-flavored markdown).
The log sits under headings like "## 15 min log 11/1" or "<h2>15 min log 10/25</h2>", newest first. Each bullet
(<li>) is one block: a clock time ("7:59 am", "1033", "437", "12 am", "Stopped working 9:15") then actions split
by "/". Rows carry: log_date, heading_date, block_start, block_index, position, action_text and flags
(blank, stopped_working, filled_by_claude, date_suspect).

Date labels are fixed conservatively and the page is never edited:
- a heading whose date repeats, or breaks the newest-first order, is flagged date_suspect;
- two neighbouring headings with the same date whose times overlap are two different days. The top one moves
  to the page's last-edited date when it is the topmost log heading and its times fit before the edit time;
  otherwise the lower one moves to the day before when that day's section sits right under it and its times
  come after that day's last block (the evening of the day before);
- anything else stays as written, flagged.
"""
import argparse
import datetime as dt
import json
import re
import sys

from shared import et
from tools.time_ledger import common as C

LOG_HEAD = re.compile(r"^\W{0,4}15\s*-?\s*min(?:ute)?s?\s*log\b[\s:\-]*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?",
                      re.I)
MD_HEAD = re.compile(r"^\s{0,3}#{1,4}\s+(.*?)\s*#*\s*$")
HTML_HEAD = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.S | re.I)
LI = re.compile(r"(<li\b[^>]*>.*?</li>)", re.S | re.I)
MD_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?!\[[ xX]\])(.*)$")

AP = r"(?P<ap>[ap]\.?\s?m\b\.?)"
T_COLON = re.compile(r"^\s*(?P<h>\d{1,2})[:.](?P<m>\d{2})\s*" + AP + "?", re.I)
T_HOUR = re.compile(r"^\s*(?P<h>\d{1,2})\s*" + AP, re.I)
T_BARE = re.compile(r"^\s*(?P<hm>\d{3,4})(?=\s*(?:/|$|[ap]\.?\s?m\b))\s*" + AP + "?", re.I)
STOP_LEAD = re.compile(r"^\s*(?:stop(?:ped|ping)?\s+)+work(?:ing)?\b\s*(?:at\s+)?", re.I)
STOP_ACT = re.compile(r"^(?:and\s+)?(?:(?:stop(?:ped|ping)?\s+)+work(?:ing)?\b|(?:taking|took|take)\s+a\s+break\b)"
                      r"|^\(?[^()]{0,40}\b(?:had to take|took|taking|take) a break\b[^()]*\)?$", re.I)
DONE_AT = re.compile(r"^(?:[\w.]+\s+){0,2}(?:done|finished)\s+(?:at\s+)?(?P<t>\d{1,2}:\d{2}\s*(?:[ap]\.?\s?m\b\.?)?)$",
                     re.I)
RESUME = re.compile(r"^(?:ok(?:ay)?,?\s+)?(?:(?:getting|got|came|coming|went)\s+)?back(?:\s+to\s+work)?"
                    r"(?:\s+(?:at\s+)?(?P<t>\d{1,2}(?::\d{2})?\s*(?:[ap]\.?\s?m\b\.?)?))?\s*[.!]?$", re.I)
CLAUDE_NOTE = re.compile(r"filled in by claude", re.I)
DAY_START_MIN = 5 * 60          # a work day runs to about 4am; an am time of 5:00 or later is a new morning


# ---------------------------------------------------------------- load

def load_page(raw):
    """Fetch result (JSON) or markdown -> (content text, last-edited ISO or None)."""
    raw = raw.lstrip("\ufeff")
    edited = None
    m = re.search(r'"page_last_edited_at"\s*:\s*"([^"]+)"', raw)
    if m:
        edited = m.group(1)
    text = raw
    s = raw.strip()
    if s[:1] in "{[":
        try:
            obj = json.loads(s)
        except ValueError:
            obj = None
        for _ in range(3):
            if isinstance(obj, list):
                obj = "\n".join(str(x.get("text", "")) if isinstance(x, dict) else str(x) for x in obj)
            if isinstance(obj, dict):
                edited = edited or obj.get("page_last_edited_at")
                obj = obj.get("text", "")
            if isinstance(obj, str):
                text = obj
                t = obj.strip()
                if t[:1] in "{[":
                    try:
                        obj = json.loads(t)
                        continue
                    except ValueError:
                        pass
                break
    if not edited:
        m = re.search(r'"page_last_edited_at"\s*:\s*"([^"]+)"', text)
        edited = m.group(1) if m else None
    a, b = text.find("<content>"), text.rfind("</content>")
    if a >= 0:
        text = text[a + len("<content>"): b if b > a else None]
    return text, edited


# ---------------------------------------------------------------- sections and blocks

def _heading_date(m, base):
    mon, day, yr = int(m.group(1)), int(m.group(2)), m.group(3)
    if yr:
        y = int(yr) + (2000 if len(yr) == 2 else 0)
    else:
        y = base.year - (1 if mon > base.month + 1 else 0)
    try:
        return dt.date(y, mon, day)
    except ValueError:
        return None


def split_sections(text, base):
    text = HTML_HEAD.sub(lambda m: "\n" + "#" * int(m.group(1)) + " " + C.clean(m.group(2)) + "\n", text)
    sections, cur = [], None
    for line in text.split("\n"):
        hm = MD_HEAD.match(line)
        head_txt = C.clean(hm.group(1)) if hm else None
        if head_txt is None:
            plain = C.clean(re.sub(r"[*_]{2}", "", line))
            if LOG_HEAD.match(plain) and len(plain) < 40:
                head_txt = plain
        if head_txt is not None:
            lm = LOG_HEAD.match(head_txt)
            if lm:
                cur = {"heading": head_txt, "hdate": _heading_date(lm, base), "body": []}
                sections.append(cur)
            else:
                cur = None
            continue
        if cur is not None:
            cur["body"].append(line)
    return [s for s in sections if s["hdate"]]


def section_items(body):
    """Body text -> list of block strings, plus the count of loose notes skipped."""
    body = "\n".join(body)
    parts = LI.split(body)
    has_li = len(parts) > 1
    items, notes = [], 0
    for part in parts:
        if LI.fullmatch(part or ""):
            inner = re.sub(r"^<li\b[^>]*>|</li>$", "", part.strip(), flags=re.I)
            lines = [C.clean(x) for x in re.split(r"\n|<br\s*/?>|<p\s*/?>|</p>", inner)]
            lines = [x for x in lines if x]
            items.append(" / ".join(lines))
            continue
        for line in (part or "").split("\n"):
            c = C.clean(line)
            if not c or re.fullmatch(r"-{3,}|\*{3,}", c):
                continue
            mb = MD_BULLET.match(line)
            if mb:
                items.append(C.clean(mb.group(1)))
            elif not has_li and (T_COLON.match(c) or T_HOUR.match(c) or T_BARE.match(c) or STOP_LEAD.match(c)):
                items.append(c)
            else:
                notes += 1
    return items, notes


def _ap_of(s):
    return (s or "").lower().replace(".", "").replace(" ", "")[:1] or None   # 'a' / 'p' / None


def read_time(text):
    """Leading clock -> (spec or None, rest, lead_stop). spec = (hour, minute, 'a'|'p'|None)."""
    lead_stop = False
    m = STOP_LEAD.match(text)
    if m:
        lead_stop = True
        text = text[m.end():]
    for rx in (T_COLON, T_HOUR, T_BARE):
        m = rx.match(text)
        if not m:
            continue
        gd = m.groupdict()
        if gd.get("hm"):
            hm = gd["hm"]
            h, mi = int(hm[:-2]), int(hm[-2:])
        else:
            h, mi = int(gd["h"]), int(gd.get("m") or 0)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            continue
        if h == 0:
            h = 12
        return (h, mi, _ap_of(gd.get("ap")) if h <= 12 else "p"), text[m.end():], lead_stop
    return None, text, lead_stop


def parse_clock_token(tok):
    """'10:10', '9:15 pm', '3:48pm' -> spec or None."""
    spec, _, _ = read_time(tok or "")
    return spec


def candidates(spec):
    h, mi, ap = spec
    if h > 12:
        return [h * 60 + mi]
    base = (h % 12) * 60 + mi
    if ap == "a":
        return [base, base + 1440]
    if ap == "p":
        return [base + 720]
    return [base, base + 720, base + 1440]


def work_day_index(minutes):
    """Which work day a minute count belongs to: 0:00 to 4:59 still counts as the day before."""
    return (minutes - DAY_START_MIN) // 1440


def resolve_clock(spec, prev, nxt=None):
    """Pick am/pm (and past-midnight) for a spec given the previous block's minutes. Returns (minutes, rollover).
    rollover is True when the time lands on a new morning (5:00 am or later on a later work day)."""
    if spec is None:
        return None, False
    cands = candidates(spec)
    h, mi, ap = spec
    if prev is None:
        if ap or h > 12:
            return cands[0], False
        if nxt is not None:
            fit = [c for c in cands if c <= nxt + 15]
            return (max(fit) if fit else min(cands)), False
        return (cands[0] if 5 <= h <= 11 else (h % 12) * 60 + mi + 720), False
    if max(cands) < prev - 15:
        if ap == "p" or h > 12:
            return cands[-1], False                   # a pm time written out of order: keep it on this day
        while max(cands) < prev - 15:                 # a second or third new morning in one section
            cands = cands + [c + 1440 for c in cands if c + 1440 > max(cands)]
    pick = min(c for c in cands if c >= prev - 15)
    return pick, work_day_index(pick) > work_day_index(prev)


def split_actions(rest):
    s = re.sub(r"(?<=\d)/(?=\d)", "\x00", rest)
    out = []
    for part in s.split("/"):
        part = part.replace("\x00", "/")
        for sub in re.split(r",?\s+and then\s+", part, flags=re.I):
            t = re.sub(r"^[\s.,;:\-]+|[\s,;:\-]+$", "", C.clean(sub))
            t = re.sub(r"\.+$", "", t).strip()
            if t:
                out.append(t)
    return out


def parse_block(text):
    """One bullet -> dict(spec, lead_stop, stop_note, resume, actions[(text, type)], claude_note)."""
    spec, rest, lead_stop = read_time(text)
    acts = split_actions(rest)
    blk = {"spec": spec, "lead_stop": lead_stop, "resume": None, "actions": [], "claude_note": False,
           "label": "", "done_at": []}
    if spec:
        h, mi, ap = spec
        blk["label"] = "%d:%02d%s" % (h, mi, (" " + ap + "m") if ap else "")
    if lead_stop:
        note = ""
        if acts and acts[0].startswith("("):
            note = " " + acts.pop(0)
        label = (" " + blk["label"]) if spec else ""
        blk["actions"].append(("Stopped working" + label + note, "break"))
    for a in acts:
        dm = DONE_AT.match(a)
        if dm and blk["actions"]:
            blk["done_at"].append((len(blk["actions"]) - 1, parse_clock_token(dm.group("t"))))
            continue
        rm = RESUME.match(a)
        if rm:
            if rm.group("t") and blk["resume"] is None:
                blk["resume"] = parse_clock_token(rm.group("t"))
            continue
        if CLAUDE_NOTE.search(a) and len(a) < 80:
            blk["claude_note"] = True
            continue
        blk["actions"].append((a, "break" if STOP_ACT.match(a) else "action"))
    return blk


# ---------------------------------------------------------------- dates

def _edit_et(edited):
    """Last edit as (work day, minutes since that day's midnight). Before 4am ET counts as the day before."""
    d = et.parse(edited) if edited else None
    if not d:
        return None, None
    e = et.to_et(d)
    day, mins = e.date(), e.hour * 60 + e.minute
    if e.hour < 4:
        day, mins = day - dt.timedelta(days=1), mins + 1440
    return day, mins


def resolve_sections(sections, edited):
    edate, emin = _edit_et(edited)
    n = len(sections)
    for s in sections:
        s["resolved"], s["suspect"], s["notes"] = s["hdate"], False, []
        nr = s.get("nroll", 0)
        first = [b["min"] for b in s["blocks"] if b["min"] is not None and b.get("offset", 0) == 0]
        last = [b["min"] - 1440 * nr for b in s["blocks"] if b["min"] is not None and b.get("offset", 0) == nr]
        s["first"] = min(first) if first else None
        s["last"] = max(last) if last else None
    for i, s in enumerate(sections):
        if any(j != i and t["hdate"] == s["hdate"] for j, t in enumerate(sections)):
            s["suspect"] = True
            s["notes"].append("heading date repeats")
        if i > 0 and s["hdate"] > sections[i - 1]["hdate"]:
            s["suspect"] = True
            s["notes"].append("newer than the heading above it")
        if i + 1 < n and s["hdate"] < sections[i + 1]["hdate"]:
            s["suspect"] = True
            s["notes"].append("older than the heading below it")
        if s.get("nroll"):
            s["suspect"] = True
            s["notes"].append("times start over on a new morning inside the section, so it holds %d days" %
                              (s["nroll"] + 1))
    for i in range(n - 1):
        up, lo = sections[i], sections[i + 1]
        if up["hdate"] != lo["hdate"]:
            continue
        d = up["hdate"]
        if up["first"] is None or lo["last"] is None:
            up["notes"].append("could not tell which day (no times); left as written")
            continue
        if up["first"] >= lo["last"] - 10:
            up["notes"].append("same day split in two sections")
            continue
        target = (edate - dt.timedelta(days=up.get("nroll", 0))) if edate else None
        if i == 0 and target and 1 <= (target - d).days <= 3 and \
                (emin is None or up["last"] is None or up["last"] <= emin + 10):
            up["resolved"] = target
            up["notes"].append("moved to %s, so its last day is %s, the day the page was last edited" % (
                target.isoformat(), edate.isoformat()) if up.get("nroll") else
                "moved to %s, the day the page was last edited" % edate.isoformat())
            continue
        if i > 0 and (sections[i - 1]["resolved"] - d).days == 2 + up.get("nroll", 0):
            up["resolved"] = d + dt.timedelta(days=1)
            up["notes"].append("moved to %s, the only day between the headings around it" %
                               up["resolved"].isoformat())
            continue
        below = sections[i + 2] if i + 2 < n else None
        if below and below["hdate"] == d - dt.timedelta(days=1) and \
                (below["last"] is None or lo["first"] > below["last"]):
            lo["resolved"] = below["hdate"]
            lo["notes"].append("moved to %s: the evening of the day below" % below["hdate"].isoformat())
            continue
        up["notes"].append("could not tell which day; left as written")


# ---------------------------------------------------------------- main parse

def parse_page(raw, edited=None, today=None):
    text, found_edit = load_page(raw)
    edited = edited or found_edit
    base = _edit_et(edited)[0] or today or et.now_et().date()
    sections = split_sections(text, base)
    notes_skipped = 0
    for si, s in enumerate(sections):
        items, notes = section_items(s["body"])
        notes_skipped += notes
        blocks = [parse_block(t) for t in items]
        s["claude"] = any(b["claude_note"] for b in blocks)
        blocks = [b for b in blocks if b["actions"] or b["spec"] or b["lead_stop"]]
        prev, offset = None, 0
        for bi, b in enumerate(blocks):
            nxt = None
            if prev is None:
                for later in blocks[bi + 1:]:
                    if later["spec"] and (later["spec"][2] or later["spec"][0] > 12):
                        nxt = candidates(later["spec"])[0]
                        break
            b["min"], b["rollover"] = resolve_clock(b["spec"], prev, nxt)
            if b["min"] is not None:
                if prev is None:
                    base_day = max(0, work_day_index(b["min"]))   # a section may open after midnight
                offset = max(offset, work_day_index(b["min"]) - base_day)
                prev = b["min"]
            b["offset"] = offset
            b["resume_min"] = resolve_clock(b["resume"], b["min"])[0] if b["resume"] and b["min"] is not None \
                else None
            if b["resume_min"] is not None:
                prev = max(prev, b["resume_min"])
            b["done_min"] = {i: resolve_clock(sp, b["min"])[0] for i, sp in b["done_at"]
                             if sp and b["min"] is not None}
        s["blocks"] = blocks
        s["nroll"] = offset
        s["idx"] = si
    resolve_sections(sections, edited)

    days = {}
    for s in sections:
        for k, b in enumerate(s["blocks"]):
            off = b.get("offset", 0)
            if off:                       # a later day written under the same heading: move it to its own day
                for f in ("min", "resume_min"):
                    if b[f] is not None:
                        b[f] -= 1440 * off
                b["done_min"] = {i: v - 1440 * off for i, v in b["done_min"].items() if v is not None}
                b["offset"] = 0
                b["day_shift"] = off
            day = s["resolved"] + dt.timedelta(days=b.get("day_shift", 0))
            days.setdefault(day, []).append((s, k, b))
    rows = []
    for day in sorted(days):
        items = days[day]
        # chronological: timed blocks by clock, untimed blocks right after the block above them in the section
        keyed, last = [], {}
        for s, k, b in items:
            anchor = b["min"] if b["min"] is not None else last.get(s["idx"], -1)
            if b["min"] is not None:
                last[s["idx"]] = b["min"]
            keyed.append(((anchor, 0 if b["min"] is not None else 1, s["idx"], k), s, b))
        keyed.sort(key=lambda x: x[0])
        prev_label, untimed_n = None, 0
        for bi, (_, s, b) in enumerate(keyed):
            if b["min"] is not None:
                start, label = C.fmt_hhmm(b["min"]), C.fmt_clock(b["min"])
                prev_label, untimed_n = label, 0
            else:
                untimed_n += 1
                start = None
                label = ("after %s" % prev_label) if prev_label else ""
            anchor = start or ("after %s #%d" % (prev_label or "start", untimed_n))
            flags_base = {"blank": False, "stopped_working": False, "filled_by_claude": bool(s["claude"]),
                          "date_suspect": bool(s["suspect"])}
            acts = b["actions"] or [("", "blank")]
            for pos, (txt, typ) in enumerate(acts):
                fl = dict(flags_base)
                fl["blank"] = typ == "blank"
                fl["stopped_working"] = typ == "break"
                rows.append({
                    "log_date": day.isoformat(), "heading_date": s["hdate"].isoformat(),
                    "block_index": bi, "block_start": start, "block_label": label, "block_min": b["min"],
                    "resume_min": b["resume_min"], "lead_stop": b["lead_stop"], "raw_time": b["label"],
                    "section": s["idx"], "position": pos, "action_text": txt, "type": typ, "flags": fl,
                    "done_min": b["done_min"].get(pos),
                    "key": C.row_key(day.isoformat(), anchor, pos, txt),
                })
    summary = [{"heading": s["heading"], "heading_date": s["hdate"].isoformat(),
                "resolved": s["resolved"].isoformat(),
                "last_day": (s["resolved"] + dt.timedelta(days=s.get("nroll", 0))).isoformat(),
                "blocks": len(s["blocks"]), "suspect": s["suspect"], "notes": s["notes"]} for s in sections]
    return {"rows": rows, "sections": summary, "edited": edited, "notes_skipped": notes_skipped}


def day_counts(rows):
    out = {}
    for r in rows:
        d = out.setdefault(r["log_date"], {"rows": 0, "actions": 0, "blank": 0, "breaks": 0, "blocks": set()})
        d["rows"] += 1
        d["blocks"].add(r["block_index"])
        d["actions"] += r["type"] == "action"
        d["blank"] += r["type"] == "blank"
        d["breaks"] += r["type"] == "break"
    for d in out.values():
        d["blocks"] = len(d["blocks"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", required=True)
    ap.add_argument("--edited", help="page last-edited time (ISO); read from the fetch JSON when present")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    with open(a.page, encoding="utf-8") as f:
        res = parse_page(f.read(), a.edited)
    if a.out:
        C.write_json(a.out, res)
    for s in res["sections"]:
        flag = " SUSPECT" if s["suspect"] else ""
        print("%-22s -> %s  %2d blocks%s %s" % (s["heading"], s["resolved"], s["blocks"], flag, "; ".join(s["notes"])))
    for d, c in sorted(day_counts(res["rows"]).items()):
        print("%s  %3d rows  %2d blocks  %2d blank  %d breaks" % (d, c["rows"], c["blocks"], c["blank"], c["breaks"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
