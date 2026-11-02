"""Suggest rows for blank blocks from what else happened in that window (marked Source = inferred).

Evidence (written by the skill to /tmp/time_ledger/evidence.json, compact or raw) can be:
- Google Calendar events: the raw list_events result ({"events": [...]}) or {"source": "calendar", "start",
  "end", "title", "attendees": n}. Cancelled, all-day and declined events are skipped.
- Fathom recordings: {"source": "fathom", "date" or "start", "end", "title"}. One with only a date is used only
  when exactly one blank window that day has nothing else.
- Gmail sent mail: {"source": "gmail", "id", "title"} (title = subject). The search tool gives no send time, so
  Python reads it from the message id; {"source": "gmail", "start", "title"} also works.
- Surven HQ GoHighLevel calls: the ghl_calls.py output for the day (read by Python, no transport).

A blank block's window runs from its start to the next block's start. Meetings that overlap it become a row
each (minutes = the overlap). Sent emails and dials inside it become one row each kind. Every inferred row is
classified like a logged one and keeps a stable key per block, so a later run never adds it twice.
"""
import datetime as dt
import email.utils
import re

from shared import et
from tools.time_ledger import classify as K
from tools.time_ledger import common as C
from tools.time_ledger import ghl_calls as G

MAX_ROWS_PER_BLOCK = 4
CAL_REPLY = re.compile(r"^\s*(accepted|declined|tentatively accepted|tentative|invitation|updated invitation)"
                       r"(\s+with note)?\s*:", re.I)


def _parse_ts(ts):
    """ISO, epoch or an email Date header ('Sun, 1 Nov 2026 17:10:00 -0500') -> aware datetime or None."""
    d = et.parse(ts)
    if d is None and isinstance(ts, str) and ts.strip():
        try:
            d = email.utils.parsedate_to_datetime(ts.strip())
        except (TypeError, ValueError, IndexError):
            d = None
        if d is not None and d.tzinfo is None:
            d = et.et_to_utc(d)
    return d


def _local_minutes(ts, day):
    d = _parse_ts(ts)
    if not d:
        return None
    loc = et.to_et(d)
    return (loc.date() - day).days * 1440 + loc.hour * 60 + loc.minute


def gmail_id_time(mid):
    """A Gmail message id (16 hex digits) starts with its send time in milliseconds: id >> 20. The search tool
    gives no send time, so this is where the time comes from. Returns an aware UTC datetime or None."""
    try:
        ms = int(str(mid).strip(), 16) >> 20
    except (TypeError, ValueError):
        return None
    d = dt.datetime.fromtimestamp(ms / 1000.0, dt.timezone.utc) if ms > 0 else None
    return d if d and 2015 <= d.year <= 2100 else None


def _when(v):
    if isinstance(v, dict):
        return v.get("dateTime") or v.get("date")
    return v


def normalize(evidence):
    """Any accepted shape -> list of {source, start, end, date, title, strong}."""
    items = []

    def add_cal(e):
        if (e.get("status") or "").lower() == "cancelled":
            return
        s, en = _when(e.get("start")), _when(e.get("end"))
        if not s or len(str(s)) <= 10:                 # all-day
            return
        att = e.get("attendees") if isinstance(e.get("attendees"), list) else []
        if any(a.get("self") and (a.get("responseStatus") or "") == "declined" for a in att if isinstance(a, dict)):
            return
        others = [a for a in att if isinstance(a, dict) and not a.get("self")] if att else []
        n_att = e.get("attendees") if isinstance(e.get("attendees"), int) else len(others)
        strong = bool(n_att) or bool(e.get("conferenceUrl") or e.get("hangoutLink"))
        if not strong and (e.get("recurringEventId") or e.get("recurring")):
            return                                     # a repeating block Joey set for himself is a plan, not proof
        items.append({"source": "calendar", "start": s, "end": en, "title": (e.get("summary") or e.get("title") or
                                                                            "Calendar event").strip(),
                      "strong": strong})

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            if "events" in x and isinstance(x["events"], list):
                for e in x["events"]:
                    add_cal(e)
            elif x.get("source") == "calendar" or ("summary" in x and "start" in x):
                add_cal(x)
            elif x.get("source") in ("gmail", "fathom"):
                if x["source"] == "gmail" and CAL_REPLY.match(x.get("title") or ""):
                    return                             # an invite answer is a click, not work in that window
                start = x.get("start")
                if not start and x["source"] == "gmail" and x.get("id"):
                    t = gmail_id_time(x["id"])
                    start = t.isoformat() if t else None
                items.append({"source": x["source"], "start": start, "end": x.get("end"),
                              "date": x.get("date"), "title": (x.get("title") or "").strip(), "strong": True})
            else:
                for k, v in x.items():
                    if isinstance(v, (dict, list)) and k not in ("attendees", "start", "end"):
                        walk(v)
    walk(evidence or [])
    return items


def blank_windows(rows):
    out = []
    for r in rows:
        if r.get("type") != "blank" or r.get("block_min") is None:
            continue
        end = r.get("next_start")
        if end is None or end <= r["block_min"]:
            end = r["block_min"] + (r.get("minutes") or 15.0)
        out.append({"date": r["log_date"], "block_index": r["block_index"], "start": r["block_min"], "end": end,
                    "row": r})
    return out


def inferred_key(row, i):
    return C.row_key(row["log_date"], "inferred " + (row.get("block_start") or str(row["block_index"])), i, "")


def block_keys(row):
    """Keys that mean this blank block was already handled (its blank row or any inferred row)."""
    return {row["key"]} | {inferred_key(row, i) for i in range(MAX_ROWS_PER_BLOCK)}


def _mk(row, i, text, minutes, model, force=None):
    r = {k: row[k] for k in ("log_date", "heading_date", "block_index", "block_start", "block_label", "block_min",
                             "section")}
    r.update({"position": 100 + i, "action_text": text, "type": "action", "source": "inferred",
              "minutes": round(max(minutes, 0.5), 1), "minutes_est": True,
              "flags": dict(row["flags"], blank=True), "key": inferred_key(row, i)})
    K.label_row(r, model)
    r["needs_label"] = False
    r["confidence"] = round(min(r["confidence"], 0.6), 3)
    if force:
        r.update(force)
    return r


def infer(rows, evidence=None, ghl_by_day=None, model=None):
    """rows: estimated rows (only blanks matter). Returns new inferred rows."""
    items = normalize(evidence)
    wins = blank_windows(rows)
    out = []
    by_day = {}
    for w in wins:
        by_day.setdefault(w["date"], []).append(w)
    used_dateonly = set()
    for w in wins:
        day = C.parse_day(w["date"])
        row = w["row"]
        made = []
        meets = []
        for it in items:
            if it["source"] in ("calendar", "fathom") and it.get("start"):
                s = _local_minutes(it["start"], day)
                e = _local_minutes(it.get("end"), day) if it.get("end") else (s + 30 if s is not None else None)
                if s is None or e is None:
                    continue
                ov = min(e, w["end"]) - max(s, w["start"])
                if ov >= 5:
                    meets.append((ov, it))
        meets.sort(key=lambda x: (-int(x[1]["strong"]), -x[0]))
        strong = [m for m in meets if m[1]["strong"]]
        for ov, it in (strong or meets)[:2]:
            label = "Meeting" if it["source"] == "calendar" and it["strong"] else (
                "Recorded call" if it["source"] == "fathom" else "On the calendar")
            made.append(("%s: %s (inferred)" % (label, it["title"]), ov, None))
        sent = [it for it in items if it["source"] == "gmail" and it.get("start")
                and w["start"] <= (_local_minutes(it["start"], day) or -1) < w["end"]]
        if sent:
            subj = sent[0]["title"] or "no subject"
            made.append(("Sent %d email%s, e.g. \"%s\" (inferred)" % (len(sent), "" if len(sent) == 1 else "s",
                                                                    subj[:60]), 3.0 * len(sent), None))
        g = (ghl_by_day or {}).get(w["date"])
        if g and not g.get("unavailable"):
            s = G.summary(g, w["start"], w["end"])
            if s["dials"]:
                span = (s["last"] - s["first"] + 2) if s["first"] is not None else s["dials"]
                made.append(("Made %d calls in GoHighLevel, %d answered, %s talk min (inferred)" % (
                    s["dials"], s["answered"], s["talk_min"]), max(span, s["talk_min"] + s["dials"]),
                    {"role": "Sales", "kind": "Outreach", "ai": False}))
        if not made:
            dated = [it for it in items if it["source"] == "fathom" and not it.get("start") and
                     it.get("date") == w["date"] and id(it) not in used_dateonly]
            if dated and len([x for x in by_day[w["date"]] if x is not w]) == 0:
                used_dateonly.add(id(dated[0]))
                made.append(("Recorded call: %s (inferred, time unknown)" % dated[0]["title"], 30.0, None))
        window = max(w["end"] - w["start"], 1.0)
        total = sum(m for _, m, _ in made)
        scale = window / total if total > window else 1.0
        for i, (text, mins, force) in enumerate(made[:MAX_ROWS_PER_BLOCK]):
            out.append(_mk(row, i, text, mins * scale, model, force))
    return out


def evidence_plan(windows, cal_ids=("primary",)):
    """What the skill should look up, per day with new blank windows (kept small on purpose)."""
    plan = []
    days = {}
    for w in windows:
        days.setdefault(w["date"], []).append(w)
    for d, ws in sorted(days.items()):
        day = C.parse_day(d)
        lo = min(w["start"] for w in ws)
        hi = max(w["end"] for w in ws)
        base = dt.datetime.combine(day, dt.time(0, 0))
        s = base + dt.timedelta(minutes=int(lo))
        e = base + dt.timedelta(minutes=int(hi) + 1)
        nxt = day + dt.timedelta(days=1)
        plan.append({
            "date": d,
            "windows": ["%s to %s" % (C.fmt_clock(w["start"]), C.fmt_clock(w["end"])) for w in ws],
            "calendar": {"calendarIds": list(cal_ids), "startTime": s.strftime("%Y-%m-%dT%H:%M:%S"),
                         "endTime": e.strftime("%Y-%m-%dT%H:%M:%S"), "orderBy": "startTime"},
            # whole days: the Gmail connector returned nothing for epoch-second after:/before: (checked 2026-11-02);
            # Python keeps only the sent mail inside the blank windows
            # -to:me drops the reports and briefs Joey's own automations mail to him from his account
            "gmail_query": "in:sent -to:me after:%s before:%s" % (day.strftime("%Y/%m/%d"),
                                                                   nxt.strftime("%Y/%m/%d")),
            "fathom": {"created_after": day.isoformat() + "T00:00:00Z",
                       "created_before": (nxt + dt.timedelta(days=1)).isoformat() + "T00:00:00Z"},
        })
    return plan
