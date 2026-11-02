"""Turn the raw pull into the desk: buckets with reasons and days waiting, a ranking by closeness to money,
and the health flags. Pure functions; the CLI only reads and writes JSON.

  python3 -m tools.hq_desk.score [--raw /tmp/hq_desk/raw.json] [--out /tmp/hq_desk/desk.json]
                                 [--brief /tmp/hq_desk/brief.json] [--routines /tmp/hq_desk/routines.json]
                                 [--now 2026-11-02T11:00:00Z]

Buckets (a lead can be in several; its card shows the strongest):
  hot            wrote in during the last 72 hours and nothing from Joey since
  owed           a promise or answer is owed (Agent Promises Owed due, or "Waiting on us" in the Contact Picture)
  deciding       met or pitched, no decision yet
  rebook         missed the meeting
  stale_replied  wrote back (deal at Replied) and no touch from Joey in 48 hours or more
  warm_referral  warm referral deal still at New with no touch at all
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

from shared import et
from tools.hq_desk import profile as prof
from tools.hq_desk.pull import AUTO_SOURCES, write_json

CAP = 15
HOT_HOURS = 72
STALE_HOURS = 48
UNANSWERED_HOURS = 24
UNANSWERED_WINDOW_DAYS = 30

BUCKETS = ["hot", "deciding", "owed", "rebook", "stale_replied", "warm_referral"]
BASE = {"hot": 100, "deciding": 80, "owed": 70, "rebook": 60, "stale_replied": 50, "warm_referral": 40}
LABEL = {"hot": "Hot", "deciding": "Deciding", "owed": "Owed", "rebook": "Rebook",
         "stale_replied": "Replied, waiting", "warm_referral": "Warm referral"}

CALL_TYPES = {"TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_IVR_CALL"}
NOT_REAL = {"TYPE_INTERNAL_COMMENT", "TYPE_COMMENT", "TYPE_NO_SHOW"}
DEAD_CALL = {"canceled", "cancelled", "failed"}
CHANNEL = {"TYPE_SMS": "text", "TYPE_EMAIL": "email", "TYPE_CALL": "call", "TYPE_CAMPAIGN_CALL": "call",
           "TYPE_IVR_CALL": "call", "TYPE_LIVE_CHAT": "chat", "TYPE_WEBCHAT": "chat", "TYPE_WHATSAPP": "WhatsApp",
           "TYPE_GMB": "Google message", "TYPE_FACEBOOK": "Facebook message", "TYPE_INSTAGRAM": "Instagram message"}

DECIDING_STAGES = {"follow up", "post-tour follow-up", "proposal"}
REBOOK_STAGES = {"no show"}
REPLIED_STAGES = {"replied"}
BOOKED_STAGES = {"meeting scheduled", "confirmed", "meeting booked", "tour booked", "tour confirmed"}
PARKED_STAGES = {"wrong timing"}
DEAD_STAGES = {"not interested", "unqualified", "wrong number", "lost", "dead"}
CLIENT_STAGES = {"client", "closed", "closed won", "won"}
CANCELLED_EVENT = {"cancelled", "canceled", "invalid"}
NOSHOW_EVENT = {"noshow", "no_show", "no-show"}

EXCLUDE_TAGS = {"client", "owner-joey", "svn-test", "svn-tooltest", "test-contact-delete-me", "opted out", "opted-out",
                "svn-dnc", "svn-0-staff"}
SAID_NO_TAGS = {"price-raise-no"}        # said no: left alone for good (planner principle 31) unless they write in
DONE_AGENT_STAGES = ("dead", "closed by joey", "client")
OPT_OUT_RX = re.compile(r"^\s*(stop|stop all|unsubscribe|end|quit|remove me)\s*[.!]*\s*$", re.I)
AUTO_REPLY_RX = re.compile(r"out of (the )?office|automatic reply|auto-?reply|autoreply|undeliverable|delivery status", re.I)
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE_RX = re.compile(r"(\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                            "nov", "dec"])}


# ---------------------------------------------------------------- small helpers

def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def scrub(s):
    """No phone numbers or email addresses on the page."""
    s = EMAIL_RX.sub("[email]", str(s or ""))
    return PHONE_RX.sub("[phone]", s)


def lead_hash(location_id, contact_id):
    return hashlib.sha256(f"{location_id}:{contact_id}".encode()).hexdigest()[:12]


def clip(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(" ,.;:") + "..."


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def age_label(hours):
    if hours is None:
        return ""
    if hours < 1:
        return "under an hour"
    if hours < 24:
        return plural(int(hours), "hour")
    return plural(int(hours // 24), "day")


def hours_since(ts, now):
    d = et.parse(ts)
    return None if d is None else (now - d).total_seconds() / 3600.0


def num(v):
    """A number from a GHL value that may be a number, a numeric string or junk."""
    try:
        return float(str(v).replace(",", "").replace("$", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def flat(v):
    """A field value as plain text: lists (multi-select, checkbox) are joined."""
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v)


def code_str(v):
    """A code field value as text: 41.0 -> "41"."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return flat(v).strip()


def first_int(v):
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def parse_loose_date(s, now):
    """First date in s: 2026-09-14, 9/14, 9/14/26, Sept 14. Year inferred so the date is not far in the future."""
    s = str(s or "")
    today = et.to_et(now).date()
    m = re.search(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", s)
    mon = day = year = None
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
    else:
        m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", s, re.I)
        if m:
            mon, day = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
    if not mon:
        return None
    for y in ([year] if year else [today.year, today.year - 1]):
        try:
            d = dt.date(y, mon, day)
        except ValueError:
            return None
        if year or d <= today + dt.timedelta(days=7):
            return d
    return None


# ---------------------------------------------------------------- messages

def is_real(m):
    t = m.get("type") or ""
    return t.startswith("TYPE_") and not t.startswith("TYPE_ACTIVITY") and t not in NOT_REAL


def is_joey(m):
    """A touch from Joey: his text or email (not an automation), any call he placed, or a call he picked up."""
    if not is_real(m):
        return False
    t, d, st = m.get("type"), m.get("dir"), norm(m.get("status"))
    if t in CALL_TYPES:
        if d == "outbound":
            return st not in DEAD_CALL
        return d == "inbound" and st == "completed"
    return d == "outbound" and norm(m.get("source")) not in AUTO_SOURCES


def wants_reply(m):
    """An inbound message that a person should answer (a text, email, chat, or a missed call)."""
    if not is_real(m) or m.get("dir") != "inbound":
        return False
    if m.get("type") in CALL_TYPES:
        return norm(m.get("status")) != "completed"
    txt = (m.get("text") or "") + " " + (m.get("subject") or "")
    return not AUTO_REPLY_RX.search(txt)


def channel_of(m):
    if not m:
        return ""
    if m.get("type") in CALL_TYPES and m.get("dir") == "inbound":
        return "missed call"
    return CHANNEL.get(m.get("type"), "message")


EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def _when(m):
    return et.parse(m.get("when")) or EPOCH


def msg_facts(messages, now):
    msgs = sorted(messages or [], key=_when, reverse=True)
    last_in = next((m for m in msgs if wants_reply(m)), None)
    last_joey = next((m for m in msgs if is_joey(m)), None)
    last_out_txt = next((m for m in msgs if is_joey(m) and m.get("text")), None)
    opted_out = any(m.get("dir") == "inbound" and OPT_OUT_RX.match(m.get("text") or "") for m in msgs[:5])
    unanswered = None
    if last_in and (not last_joey or _when(last_joey) < _when(last_in)):
        unanswered = last_in
    real = [m for m in msgs if is_real(m)]
    return {
        "last_in": last_in,
        "last_in_hours": hours_since(last_in.get("when"), now) if last_in else None,
        "last_joey": last_joey,
        "last_joey_hours": hours_since(last_joey.get("when"), now) if last_joey else None,
        "last_out_text": last_out_txt,
        "unanswered": unanswered,
        "unanswered_hours": hours_since(unanswered.get("when"), now) if unanswered else None,
        "oldest_hours": hours_since(real[-1].get("when"), now) if real else None,
        "n_real": len(real),
        "opted_out": opted_out,
    }


# ---------------------------------------------------------------- the planner's memory fields

PIC_LABEL_RX = re.compile(
    r"(?i)(?:^|(?<=[\n|;.]))\s*(asked for|waiting on us|how they reach back|situation|offer pitched|"
    r"offer\s+[^:\n|]{0,24}?call|offer|zone)\s*:")


def parse_picture(text):
    """The Agent Contact Picture's parts: asked_for, waiting, reach, situation, offers (list), zone."""
    out = {"asked_for": "", "waiting": "", "reach": "", "situation": "", "offers": [], "zone": ""}
    s = str(text or "")
    marks = list(PIC_LABEL_RX.finditer(s))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(s)
        label = norm(m.group(1))
        body = s[m.end():end].strip(" \n|;")
        if label.startswith("offer"):
            if label != "offer pitched":
                out["offers"].append((m.group(1).strip() + ": " + body).strip())
            elif body:
                out["offers"] += [x.strip() for x in re.split(r"\n+", body) if x.strip()]
        else:
            key = {"asked for": "asked_for", "waiting on us": "waiting", "how they reach back": "reach",
                   "situation": "situation", "zone": "zone"}[label]
            out[key] = body
    return out


def pitched(offers):
    """True when an Offer line has a real number (not 'not pitched')."""
    for o in offers or []:
        if re.search(r"not pitched", o, re.I):
            continue
        if re.search(r"\$\s?\d|\b\d+(\.\d+)?\s?k\b|\b\d{3,}\b", o, re.I):
            return True
    return False


EMPTY_RX = re.compile(r"^\s*((none|nothing)( yet| owed| now| right now)?|n/?a|-+)\s*\.?\s*$", re.I)


def is_empty(s):
    return not str(s or "").strip() or bool(EMPTY_RX.match(str(s)))


def parse_owed_field(text, now):
    """Agent Promises Owed: '2026-09-28: said I would check back' lines. The date is the due date."""
    s = str(text or "").strip()
    if not s:
        return []
    today = et.to_et(now).date()
    items = []
    starts = list(re.finditer(r"(20\d\d-\d{2}-\d{2})\s*:?\s*", s))
    if not starts:
        parts = [p.strip(" -;|") for p in re.split(r"\n|;|\s\|\s", s)]
        return [{"text": p, "date": None, "age_days": None, "source": "promises"} for p in parts if not is_empty(p)]
    lead = s[:starts[0].start()].strip(" -;|\n")
    if lead and not is_empty(lead):
        items.append({"text": lead, "date": None, "age_days": None, "source": "promises"})
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(s)
        body = s[m.end():end].strip(" -;|\n")
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            d = None
        if body and not is_empty(body):
            items.append({"text": body, "date": d.isoformat() if d else None,
                          "age_days": (today - d).days if d else None, "source": "promises"})
    return items


def parse_waiting(waiting, now):
    """'Waiting on us' items from the picture, with who owes it and since when."""
    s = str(waiting or "").strip()
    if is_empty(s):
        return []
    today = et.to_et(now).date()
    out = []
    for part in re.split(r";|\n|\s\|\s", s):
        p = part.strip(" .-")
        if is_empty(p):
            continue
        who = ""
        if re.search(r"(,|\()\s*joey\b|\bjoey\s*\)?$", p, re.I):
            who = "Joey"
        elif re.search(r"(,|\()\s*(you|agent|us|the agent)\s*\)?$", p, re.I):
            who = "agent"
        d = parse_loose_date(p, now)
        out.append({"text": p, "date": d.isoformat() if d else None, "age_days": (today - d).days if d else None,
                    "source": "picture", "who": who})
    return out


STOP_WORDS = {"joey", "with", "that", "this", "they", "their", "promised", "since", "asked", "about", "from",
              "will", "would", "said", "send", "back"}


def _words(s):
    return {w for w in re.findall(r"[a-z]{4,}", norm(s))}


def owed_items(fields, now):
    """Everything owed to this lead that only Joey can give, oldest first. Future-dated promises are kept
    with due_in so the card can show them, but only due ones put a lead in the owed bucket."""
    a = parse_owed_field(fields.get("owed"), now)
    b = [x for x in parse_waiting(parse_picture(fields.get("picture")).get("waiting"), now) if x["who"] != "agent"]
    def same(x, y):
        wx, wy = _words(x["text"]) - STOP_WORDS, _words(y["text"]) - STOP_WORDS
        if not wx or not wy:
            return False
        if len(wx & wy) / len(wx | wy) >= 0.4:
            return True
        return bool(x["date"] and x["date"] == y["date"] and wx & wy)
    for x in b:
        if any(same(x, y) for y in a):
            continue
        a.append(x)
    for x in a:
        x["due"] = x["age_days"] is None or x["age_days"] >= -1
    a.sort(key=lambda x: (-(x["age_days"] if x["age_days"] is not None else -10 ** 6)))
    return a


def plan_log_top(text, n=3, width=280):
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    return [clip(x, width) for x in lines[:n]]


# ---------------------------------------------------------------- one lead

def lead_code(fields, tags):
    tags = {norm(t) for t in tags}
    ec, rc, pc = (code_str(fields.get(k)) for k in ("email_code", "reply_code", "partner_code"))
    if ec and ("email-reply" in tags or not rc):
        return "E" + ec
    if rc:
        return rc
    if pc:
        return "P" + pc
    return ""


def home_name(contact, fields, opps):
    for v in [contact.get("companyName"), fields.get("home")] + [o.get("companyName") for o in opps]:
        if v and str(v).strip():
            return str(v).strip()
    w = str(fields.get("whisper") or "")
    m = re.match(r"\s*([^.]{2,40})\.\s+Email\b", w)
    if m and len(m.group(1).split()) <= 5:
        return m.group(1).strip()
    return ""


def is_excluded(contact, fields, facts, codes_skip, joey_contact, code, stages=()):
    tags = {norm(t) for t in contact.get("tags") or []}
    if contact.get("id") and contact.get("id") == joey_contact:
        return "Joey's own contact"
    if tags & EXCLUDE_TAGS:
        return "tag " + sorted(tags & EXCLUDE_TAGS)[0]
    if contact.get("dnd"):
        return "do not disturb"
    for k in ("test", "suppressed"):
        v = norm(flat(fields.get(k)))
        if v and v not in ("no", "false", "0", "off", "n"):
            return k
    if set(stages) & CLIENT_STAGES:
        return "client stage"
    name = norm(f"{contact.get('firstName')} {contact.get('lastName')}")
    if name in ("test", "test test", "joey") or name.startswith("test "):
        return "test name"
    st = norm(flat(fields.get("stage")))
    if st.startswith(DONE_AGENT_STAGES):
        return "agent stage " + st
    if code and code in codes_skip:
        return "skip code"
    if facts.get("opted_out"):
        return "said stop"
    return ""


def is_parked(fields, deal_stages, now):
    if deal_stages & PARKED_STAGES:
        return True
    st = norm(flat(fields.get("stage")))
    if st.startswith("parked"):
        d = parse_loose_date(st, now)
        return d is None or d > et.to_et(now).date()
    return False


def meetings_for(cid, events, now):
    past, future = [], []
    for e in events:
        if e.get("contactId") != cid or e.get("deleted"):
            continue
        d = et.parse(e.get("start"))
        if not d:
            continue
        st = norm(e.get("status")).replace(" ", "")
        row = {"start": d.isoformat(), "status": st, "hours": (now - d).total_seconds() / 3600.0}
        if d > now and st in CANCELLED_EVENT:
            continue                      # a cancelled meeting ahead is no meeting
        (past if d <= now else future).append(row)
    past.sort(key=lambda r: r["start"], reverse=True)
    future.sort(key=lambda r: r["start"])
    return past, future


def deadline_info(deadline_et, now):
    if not deadline_et:
        return None
    try:
        naive = dt.datetime.fromisoformat(str(deadline_et))
    except ValueError:
        return None
    if naive.tzinfo:
        naive = et.to_et(naive).replace(tzinfo=None)
    utc = et.et_to_utc(naive)
    days = (naive.date() - et.to_et(now).date()).days
    label = naive.strftime("%a %b ") + str(naive.day) + ", " + fmt_clock(naive)
    return {"days_left": days, "passed": now >= utc, "label": label, "utc": utc.isoformat()}


def fmt_clock(d):
    h = d.hour % 12 or 12
    return f"{h}{'' if d.minute == 0 else ':%02d' % d.minute}{'am' if d.hour < 12 else 'pm'}"


def fmt_et(ts):
    d = ts if isinstance(ts, dt.datetime) else et.parse(ts)
    if d is None:
        return ""
    d = et.to_et(d)
    return d.strftime("%a %b ") + str(d.day) + ", " + fmt_clock(d)


def build_lead(cid, contact, opps, block, events, stage_name, now, deadline, raw):
    fields = contact.get("fields") or {}
    facts = msg_facts(block.get("messages"), now)
    code = lead_code(fields, contact.get("tags") or [])
    open_opps = [o for o in opps if o.get("status") == "open"]
    stages = {norm(stage_name.get(o.get("stageId"), "")) for o in open_opps}
    excluded = is_excluded(contact, fields, facts, set(raw.get("skip_codes") or []), raw.get("joey_contact"), code,
                           stages)
    tags = {norm(t) for t in contact.get("tags") or []}
    pic = parse_picture(fields.get("picture"))
    offers = pic["offers"]
    is_pitched = pitched(offers)
    owed = owed_items(fields, now)
    past, future = meetings_for(cid, events, now)
    parked = is_parked(fields, stages, now)
    agent_stage = norm(flat(fields.get("stage")))
    first = flat(fields.get("preferred") or contact.get("firstName") or "").strip()
    if not first:
        first = (opps[0].get("contactName") or "").split(" ")[0] if opps else ""
    on_raise = "price-raise" in tags and "price-raise-no" not in tags
    raise_live = bool(deadline and not deadline["passed"])
    beds = first_int(fields.get("beds"))
    buckets, why, waits = [], {}, {}
    attended = [p for p in past if p["status"] not in CANCELLED_EVENT | NOSHOW_EVENT]
    # a meeting is still ahead (on the meeting calendar, by deal stage, or by the planner's Agent Stage)
    booked = bool(future) or bool(stages & BOOKED_STAGES) or agent_stage.startswith("booked")
    # every open deal sits in a dead stage (Not Interested, Unqualified, Wrong Number): only hot and owed apply
    dead = (bool(stages) and stages <= DEAD_STAGES) or bool(tags & SAID_NO_TAGS)
    last_noshow = bool(past) and past[0]["status"] in NOSHOW_EVENT

    # hot
    if facts["unanswered"] and facts["unanswered_hours"] is not None and facts["unanswered_hours"] <= HOT_HOURS:
        ch = channel_of(facts["unanswered"])
        buckets.append("hot")
        waits["hot"] = facts["unanswered_hours"] / 24.0
        why["hot"] = (f"Called you {age_label(facts['unanswered_hours'])} ago and missed you. Nothing back yet."
                      if ch == "missed call" else
                      f"Wrote by {ch} {age_label(facts['unanswered_hours'])} ago. No reply from you yet.")

    # owed
    due = [x for x in owed if x["due"]]
    if due:
        buckets.append("owed")
        oldest = max((x["age_days"] for x in due if x["age_days"] is not None), default=None)
        waits["owed"] = float(oldest) if oldest is not None else 0.0
        first_item = due[0]["text"].rstrip(".")
        extra = f" (+{len(due) - 1} more)" if len(due) > 1 else ""
        why["owed"] = (f"You owe: {first_item}{extra}. "
                       + (f"Waiting {plural(oldest, 'day')}." if oldest is not None and oldest > 0 else "Due now."))

    if not parked and not dead:
        # deciding
        if not booked and not (stages & REBOOK_STAGES) and not last_noshow and (
                stages & DECIDING_STAGES or agent_stage.startswith("thinking it over") or is_pitched):
            buckets.append("deciding")
            d_days = None
            if attended:
                d_days = attended[0]["hours"] / 24.0
            else:
                od = [parse_loose_date(o, now) for o in offers]
                od = [x for x in od if x]
                if od:
                    d_days = float((et.to_et(now).date() - max(od)).days)
                else:
                    ch = [et.parse(o.get("lastStageChangeAt")) for o in open_opps
                          if norm(stage_name.get(o.get("stageId"), "")) in DECIDING_STAGES]
                    ch = [x for x in ch if x]
                    if ch:
                        d_days = (now - max(ch)).total_seconds() / 86400.0
            waits["deciding"] = d_days if d_days is not None else 0.0
            s = f"Met {plural(int(d_days), 'day')} ago" if d_days is not None else "Met you"
            s += ", heard the offer" if is_pitched else ""
            s += ". No decision yet."
            if on_raise and raise_live:
                s += f" On the price raise list, {plural(deadline['days_left'], 'day')} left."
            why["deciding"] = s

        # rebook
        if (stages & REBOOK_STAGES or agent_stage.startswith(("no-show", "no show")) or last_noshow) and not booked:
            buckets.append("rebook")
            r_days = past[0]["hours"] / 24.0 if past else None
            if r_days is None:
                ch = [et.parse(o.get("lastStageChangeAt")) for o in open_opps
                      if norm(stage_name.get(o.get("stageId"), "")) in REBOOK_STAGES]
                ch = [x for x in ch if x]
                r_days = (now - max(ch)).total_seconds() / 86400.0 if ch else None
            waits["rebook"] = r_days if r_days is not None else 0.0
            why["rebook"] = (f"Missed the meeting {plural(int(r_days), 'day')} ago." if r_days is not None
                             else "Missed the meeting.") + " Not rebooked."

        # stale replied
        if stages & REPLIED_STAGES:
            jh = facts["last_joey_hours"]
            if jh is None or jh >= STALE_HOURS:
                buckets.append("stale_replied")
                if jh is not None:
                    waits["stale_replied"] = jh / 24.0
                    why["stale_replied"] = f"Wrote back. No touch from you in {age_label(jh)}."
                else:
                    created = [et.parse(o.get("createdAt")) for o in open_opps
                               if norm(stage_name.get(o.get("stageId"), "")) in REPLIED_STAGES]
                    created = [x for x in created if x]
                    days = (now - min(created)).total_seconds() / 86400.0 if created else 0.0
                    waits["stale_replied"] = days
                    why["stale_replied"] = (f"Wrote back {plural(int(days), 'day')} ago. No touch from you yet."
                                            if days >= 1 else "Wrote back. No touch from you yet.")

        # warm referral untouched
        for o in open_opps:
            if o.get("pipeline") == "warm_referral" and norm(stage_name.get(o.get("stageId"), "")) == "new":
                created = et.parse(o.get("createdAt"))
                if facts["last_joey"] and created and et.parse(facts["last_joey"].get("when")) >= created:
                    continue
                if facts["last_joey"] and not created:
                    continue
                days = (now - created).total_seconds() / 86400.0 if created else 0.0
                buckets.append("warm_referral")
                waits["warm_referral"] = days
                why["warm_referral"] = (f"Warm referral, in for {plural(int(days), 'day')}. No touch yet."
                                        if days >= 1 else "Warm referral, came in today. No touch yet.")
                break

    primary = max(buckets, key=lambda b: BASE[b]) if buckets else None
    score = 0.0
    if primary:
        score = BASE[primary] + 8 * (len(buckets) - 1)
        score += 10 if is_pitched else 0
        score += 5 if (on_raise and raise_live) else 0
        score += min(beds or 0, 30) / 3.0
        score += min(max(num(o.get("value")) for o in open_opps) / 1000.0, 10) if open_opps else 0
        w = waits.get(primary) or 0.0
        if primary == "hot":
            score += max(0.0, (HOT_HOURS - w * 24) / 12.0)
        elif primary == "owed":
            score += min(w, 42) / 4.0
        else:
            score -= min(w, 60) / 6.0

    # what to do next, in Joey's words
    action = ""
    if primary == "hot":
        ch = channel_of(facts["unanswered"])
        if "deciding" in buckets or is_pitched:
            action = "They are deciding and just wrote in. Call now, then answer what they asked."
        elif ch == "missed call":
            action = "Call them back now."
        else:
            action = f"Answer their {ch} today. A quick call is better if they asked a question."
    elif primary == "deciding":
        action = "Ask for the decision. One short question."
        if on_raise and raise_live:
            action += f" Price goes up {deadline['label']} their time."
    elif primary == "owed":
        action = "Send what you promised. The draft is below if it could be written."
    elif primary == "rebook":
        action = "Text to rebook the meeting. Ask what day works."
    elif primary == "stale_replied":
        action = "Answer their reply and ask for a quick call."
    elif primary == "warm_referral":
        action = "First text today. Say who referred them if the record shows it."

    in_pipes = {o.get("pipeline") for o in open_opps}
    last_ch = channel_of(facts["unanswered"] or facts["last_in"])
    suggest = ["email"] if (last_ch == "email" or ("email" in in_pipes and "leadsuite" not in in_pipes)) else ["sms"]

    chips = []
    if on_raise and raise_live:
        chips.append("price raise")
    if "price-raise-replied" in tags:
        chips.append("answered price raise")
    if "reactivation" in tags and "reactivation-paused" not in tags:
        chips.append("reactivation")
    if is_pitched:
        chips.append("pitched")
    if beds:
        chips.append(plural(beds, "bed"))
    if future:
        chips.append("meeting " + fmt_et(future[0]["start"]))
    if parked:
        chips.append("parked")

    said = None
    src = facts["unanswered"] or facts["last_in"]
    if src and src.get("text") and (hours_since(src.get("when"), now) or 1e9) <= 24 * 14:
        said = {"channel": channel_of(src), "ago": age_label(hours_since(src.get("when"), now)),
                "text": clip(scrub(src.get("text")), 220)}

    deal_lines = [f"{o.get('pipeline')}: {stage_name.get(o.get('stageId'), '?')} ({o.get('status')})" for o in opps]
    li, lo = facts["last_in"], facts["last_out_text"]
    context = {
        "deals": deal_lines,
        "agent_stage": fields.get("stage") or "",
        "next_touch": fields.get("next") or "",
        "callback_at": fields.get("callback_at") or "",
        "whisper": clip(flat(fields.get("whisper")), 240),
        "picture": str(fields.get("picture") or "")[:1400],
        "plan_log": plan_log_top(fields.get("log")),
        "offers": offers,
        "beds": fields.get("beds") or "",
        "community": fields.get("community") or "",
        "zone": fields.get("tz") or contact.get("timezone") or pic.get("zone") or "",
        "tags": sorted(t for t in tags if t.startswith(("price-raise", "reactivation", "email-reply", "referral",
                                                         "leadsuite", "preapproved"))),
        "last_inbound": ({"when": fmt_et(li["when"]), "channel": channel_of(li), "text": li.get("text") or "",
                          "subject": li.get("subject") or ""} if li else None),
        "last_from_joey": ({"when": fmt_et(lo["when"]), "channel": channel_of(lo), "text": lo.get("text") or ""}
                           if lo else None),
        "last_touch_hours": round(facts["last_joey_hours"], 1) if facts["last_joey_hours"] is not None else None,
        "last_touch": ({"when": fmt_et(facts["last_joey"]["when"]), "channel": channel_of(facts["last_joey"]),
                        "status": facts["last_joey"].get("status") or ""} if facts["last_joey"] else None),
        "last_meeting": ({"when": fmt_et(past[0]["start"]), "status": past[0]["status"]} if past else None),
        "next_meeting": ({"when": fmt_et(future[0]["start"]), "status": future[0]["status"]} if future else None),
        "price_raise": {"on_list": on_raise, "days_left": deadline["days_left"] if deadline else None,
                        "deadline": deadline["label"] if deadline else ""},
    }
    return {
        "id": cid,
        "hash": lead_hash(raw.get("location_id"), cid),
        "first": first,
        "home": home_name(contact, fields, opps),
        "code": code,
        "excluded": excluded,
        "parked": parked,
        "buckets": buckets,
        "primary": primary,
        "label": LABEL.get(primary, ""),
        "why": [why[b] for b in sorted(buckets, key=lambda b: -BASE[b])],
        "waiting_days": round(waits.get(primary, 0.0), 2) if primary else None,
        "waiting": (age_label(waits[primary] * 24) if primary and waits.get(primary) else "") or
                   ("today" if primary else ""),
        "action": action,
        "suggest": suggest,
        "chips": chips,
        "owed": [{k: x.get(k) for k in ("text", "date", "age_days", "source", "due")} for x in owed],
        "said": said,
        "unanswered_hours": facts["unanswered_hours"],
        "score": round(score, 2),
        "context": context,
        "drafts": {},
    }


# ---------------------------------------------------------------- the whole desk

def health_flags(raw, leads, now, deadline, routines=None):
    flags = []
    evs = [e for e in raw.get("events") or [] if not e.get("deleted")
           and norm(e.get("status")).replace(" ", "") not in CANCELLED_EVENT]
    upcoming = []
    for e in evs:
        d = et.parse(e.get("start"))
        if d and now <= d <= now + dt.timedelta(days=7):
            upcoming.append(d)
    n7 = len(upcoming)
    flags.append({"key": "meetings_next7", "level": "red" if n7 == 0 else "ok", "count": n7,
                  "text": (f"{plural(n7, 'discovery call')} booked in the next 7 days."
                           if n7 else "0 discovery calls booked in the next 7 days.")})

    created = [et.parse(o.get("createdAt")) for o in raw.get("opportunities") or []]
    created = [c for c in created if c]
    if created:
        days = int((now - max(created)).total_seconds() // 86400)
        lvl = "red" if days >= 7 else ("amber" if days >= 3 else "ok")
        flags.append({"key": "last_new_lead", "level": lvl, "count": days,
                      "text": ("Last new lead came in today." if days == 0 else
                               f"Last new lead came in {plural(days, 'day')} ago.")})

    live = [l for l in leads if not l["excluded"]]
    stale = [l for l in live if "stale_replied" in l["buckets"]]
    flags.append(stale_flag(len(stale), [l["code"] for l in stale if l["code"]],
                            [[l["hash"], l["code"]] for l in stale]))

    if deadline and not deadline["passed"]:
        d = deadline["days_left"]
        flags.append({"key": "price_raise", "level": "red" if d <= 3 else ("amber" if d <= 7 else "info"), "count": d,
                      "text": (f"Price raise ends today, {deadline['label']} their time." if d == 0 else
                               f"Price raise deadline in {plural(d, 'day')}: {deadline['label']} their time.")})

    unans = [l for l in live if l["unanswered_hours"] is not None
             and UNANSWERED_HOURS <= l["unanswered_hours"] <= UNANSWERED_WINDOW_DAYS * 24]
    unans.sort(key=lambda l: -l["unanswered_hours"])
    flags.append(unanswered_flag(len(unans), [l["code"] for l in unans if l["code"]],
                                 [[l["hash"], l["code"]] for l in unans]))

    if routines is not None:
        flags.append(routine_flag(routines))

    errs = [e for e in raw.get("errors") or [] if e and e[0] != "bound"]
    if errs:
        flags.append({"key": "data", "level": "amber", "count": len(errs),
                      "text": f"{plural(len(errs), 'read')} from GoHighLevel failed, so this list may be short."})
    return sort_flags(flags)


FLAG_ORDER = {"red": 0, "amber": 1, "info": 2, "ok": 3}


def sort_flags(flags):
    return sorted(flags, key=lambda f: FLAG_ORDER.get(f["level"], 9))


def routine_flag(routines):
    """routines: [{name, status}] from list_triggers (last_run.status), or {"unavailable": "why"}."""
    if isinstance(routines, dict):
        return {"key": "routines", "level": "info", "count": 0,
                "text": "Could not check the other routines today: " + str(routines.get("unavailable") or "no tool") + "."}
    bad = [r for r in routines or [] if norm(r.get("status")) in ("failed", "error", "timed_out", "timeout", "errored")]
    if bad:
        return {"key": "routines", "level": "red", "count": len(bad),
                "text": "Last run failed: " + ", ".join(str(r.get("name") or "a routine") for r in bad[:5]) + "."}
    return {"key": "routines", "level": "ok", "count": 0,
            "text": f"Every Surven routine ran fine last time ({plural(len(routines or []), 'checked', 'checked')})."}


def stale_flag(n, codes, ids):
    return {"key": "stale_replied", "level": "red" if n >= 5 else ("amber" if n else "ok"), "count": n,
            "text": (f"{plural(n, 'reply', 'replies')} waiting with no touch from you in 2+ days."
                     if n else "Every reply has had a touch in the last 2 days."),
            "codes": codes[:12], "ids": ids}


def unanswered_flag(n, codes, ids):
    return {"key": "unanswered", "level": "red" if n else "ok", "count": n,
            "text": (f"{plural(n, 'lead')} wrote in and got no answer for over 24 hours."
                     if n else "No message has waited over 24 hours."),
            "codes": codes[:12], "ids": ids}


def apply_hides(desk):
    """Take leads the drafting pass hid (auto reply, client, never work) out of the counted flags.
    Idempotent: it works from the full id list each flag keeps."""
    hidden = {l["hash"] for l in desk.get("items", []) if (l.get("drafts") or {}).get("hide")}
    makers = {"stale_replied": stale_flag, "unanswered": unanswered_flag}
    flags = []
    for f in desk.get("health") or []:
        if f.get("key") in makers and "ids" in f:
            keep = [x for x in f["ids"] if x[0] not in hidden]
            f = makers[f["key"]](len(keep), [c for _, c in keep if c], f["ids"])
        flags.append(f)
    desk["health"] = sort_flags(flags)
    return desk


def apply_routines(desk, routines):
    """Add or replace the routines flag on an already scored desk."""
    flags = [f for f in desk.get("health") or [] if f["key"] != "routines"]
    flags.append(routine_flag(routines))
    desk["health"] = sort_flags(flags)
    return desk


def build(raw, now=None, routines=None, cap=CAP):
    now = now or et.now_utc()
    deadline = deadline_info(raw.get("deadline_et"), now)
    stage_name = {}
    for p in raw.get("pipelines") or []:
        for s in p.get("stages") or []:
            stage_name[s.get("id")] = s.get("name") or ""
    by_contact = {}
    for o in raw.get("opportunities") or []:
        by_contact.setdefault(o.get("contactId"), []).append(o)
    leads = []
    for cid, contact in (raw.get("contacts") or {}).items():
        opps = by_contact.get(cid) or []
        if not any(o.get("status") == "open" for o in opps):
            continue
        block = (raw.get("conversations") or {}).get(cid) or {}
        leads.append(build_lead(cid, contact, opps, block, raw.get("events") or [], stage_name, now, deadline, raw))
    ranked = sorted([l for l in leads if l["primary"] and not l["excluded"]], key=lambda l: (-l["score"], l["id"]))
    counts = {b: sum(1 for l in ranked if b in l["buckets"]) for b in BUCKETS}
    counts["owed_items"] = sum(sum(1 for x in l["owed"] if x["due"]) for l in ranked)
    counts["open_contacts"] = len(leads)
    counts["excluded"] = sum(1 for l in leads if l["excluded"])
    counts["candidates"] = len(ranked)
    flags = health_flags(raw, leads, now, deadline, routines)
    n7 = next((f["count"] for f in flags if f["key"] == "meetings_next7"), 0)
    shown = ranked[:cap]
    return {
        "generated_at": now.isoformat(),
        "generated_et": fmt_et(now),
        "location_key": raw.get("location_key"),
        "location_id": raw.get("location_id"),
        "deadline": deadline,
        "counts": counts,
        "top": {"call_today": sum(1 for l in shown if {"hot", "deciding"} & set(l["buckets"])),
                "owed_items": sum(sum(1 for x in l["owed"] if x["due"]) for l in shown),
                "booked_next_7": n7},
        "health": flags,
        "items": ranked,
        "cap": cap,
        "fatal": raw.get("fatal") or "",
        "errors": (raw.get("errors") or [])[:20],
    }


def brief(desk, n=CAP):
    """What the model needs to write drafts: the top leads with their context, nothing else."""
    out = {"generated_et": desk["generated_et"], "deadline": desk.get("deadline"), "leads": []}
    for l in desk["items"][:n]:
        out["leads"].append({k: l[k] for k in ("id", "first", "home", "code", "primary", "buckets", "why", "waiting",
                                                "action", "suggest", "chips")}
                            | {"owed": [dict(x, i=i) for i, x in enumerate(y for y in l["owed"] if y["due"])],
                               "context": l["context"]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score the HQ desk from the raw pull.")
    ap.add_argument("--raw", default=os.path.join(prof.OUT_DIR, "raw.json"))
    ap.add_argument("--out", default=os.path.join(prof.OUT_DIR, "desk.json"))
    ap.add_argument("--brief", default=os.path.join(prof.OUT_DIR, "brief.json"))
    ap.add_argument("--routines", help="JSON list of {name, status} from list_triggers (failed runs become a flag)")
    ap.add_argument("--now", help="ISO time to score as of (tests)")
    a = ap.parse_args(argv)
    with open(a.raw, encoding="utf-8") as f:
        raw = json.load(f)
    routines = None
    if a.routines and os.path.exists(a.routines):
        with open(a.routines, encoding="utf-8") as f:
            routines = json.load(f)
    desk = build(raw, now=et.parse(a.now) if a.now else None, routines=routines)
    write_json(a.out, desk)
    write_json(a.brief, brief(desk), indent=None)
    c = desk["counts"]
    print(f"desk: {c['candidates']} leads ranked ({c['hot']} hot, {c['deciding']} deciding, {c['owed']} owed, "
          f"{c['rebook']} rebook, {c['stale_replied']} replied waiting, {c['warm_referral']} warm referral); "
          f"red flags: {sum(1 for f in desk['health'] if f['level'] == 'red')} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
