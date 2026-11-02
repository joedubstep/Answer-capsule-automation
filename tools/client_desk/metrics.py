"""Pure metric functions for the Client Desk. No network: everything reads the raw pull (tools/client_desk/pull.py).

Who is who (classify):
  internal        Joey, staff, the owner, the home's own line, test records (tags svn-0-staff, svn-test, owner-joey;
                  a name with the word "test"; the alert contacts in config; a phone or email that belongs to a user
                  of the location or to the location itself; an email at Surven's or the home's own domain).
  partner         a referral partner: tag referral-partner or any partner-* tag, a deal in the partner pipeline, or an
                  Agent Stage that starts "partner:". (The AGC collector's known bug is that it counts these as families.)
  not_family      Agent Stage "not a family: ...", SVN Call Outcome Not Qualified or Wrong Number, tag job-seeker.
  before_start    added before the client's start date (Splendor's location was a sandbox before go-live).
  unknown_caller  no real name and not judged yet (Agent Stage blank or "new"): the planner's "Caller 1234" questions.
  family          everyone else: a real family (the AGC collector's rule, minus partners and internal records).

Every count is a plain count of records. Zero is zero; nothing is estimated.
"""
import datetime as dt
import hashlib
import re
import statistics

from shared import et

CALL_TYPES = {"TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_IVR_CALL"}
TEXT_TYPES = {"TYPE_SMS", "TYPE_CAMPAIGN_SMS"}
EMAIL_TYPES = {"TYPE_EMAIL", "TYPE_CAMPAIGN_EMAIL"}
CHAT_TYPES = {"TYPE_LIVE_CHAT", "TYPE_WEBCHAT"}
NOT_SENT = {"failed", "undelivered", "canceled", "cancelled", "scheduled", "pending"}
NOT_PLACED = {"failed", "canceled", "cancelled"}   # an outbound call that never rang (live: 18 workflow calls in 45 days)
MISSED_CALL = {"no-answer", "noanswer", "busy", "voicemail", "missed", "failed", "canceled", "cancelled"}
# The weekly open rooms email to partners (every subject seen live). It is a bulk send, so it is never a check-in,
# a thank-you or a first answer to someone.
OPEN_BEDS_SUBJECT = re.compile(r"rooms?\s+(?:open\s+)?this\s+week|open\s+(?:beds|rooms)|referral\s+sheet|"
                               r"discharges?\s+this\s+week|coming\s+up\s+for\s+discharge", re.I)
TALK_SECONDS = 60
INTERNAL_TAGS = {"svn-0-staff", "svn-test", "owner-joey"}
HELD_TAGS = {"svn-tour-showed", "svn-tour-arrived"}
NOSHOW_TAGS = {"svn-tour-noshow"}
TOURED_STAGES = ("tour attended", "post-tour follow-up", "move-in pending")
NO_ANSWER_NEEDED = re.compile(r"^\s*(ok|okay|k|thanks|thank you|thank you!|ty|got it|sounds good|stop|unsubscribe|"
                              r"stop all|end|quit|cancel)\W*$", re.I)
# A closing line that needs no answer when it asks nothing: "Thanks received.", "It was a pleasure speaking with you".
CLOSER = re.compile(r"^\W*(thanks|thank you|thx|ty|received|got it|noted|will do|sounds good|you're welcome|"
                    r"you are welcome|it was (a pleasure|nice|great|good) (speaking|talking|meeting|chatting)|"
                    r"(nice|great|good) (speaking|talking|meeting|chatting))\b", re.I)
AUTO_REPLY = re.compile(r"automatic reply|auto.?reply|out of (the )?office|away from (the )?office|undeliverable|"
                        r"delivery status notification|mail delivery", re.I)
PARTNER_ON_LIST = ("yes partner", "info sent", "sent a referral")


# ---------------------------------------------------------------- time

def ts(v):
    return et.parse(v)


def window(now, days=7):
    return now - dt.timedelta(days=days), now


def inside(v, start, end):
    t = ts(v)
    return t is not None and start <= t < end


def et_date_start(day_iso):
    try:
        d = dt.date.fromisoformat(day_iso)
    except (TypeError, ValueError):
        return None
    return et.et_to_utc(dt.datetime(d.year, d.month, d.day))


def fmt_day(t):
    t = et.to_et(t) if t else None
    return "%s %d" % (t.strftime("%a %b"), t.day) if t else ""


# ---------------------------------------------------------------- names and codes

def family_code(cid):
    """Same code as the AGC collector (code_for): F plus 6 hex characters of the contact id's hash."""
    return "F" + hashlib.sha256(cid.encode()).hexdigest()[:6].upper()


def place(c, deal=None):
    """A partner goes by its place: the company name up to the first comma or bracket (planner rules.md)."""
    for s in ((c or {}).get("company"), (deal or {}).get("company"), (deal or {}).get("name")):
        s = (s or "").strip()
        if s:
            return re.split(r"[,(\[]", s)[0].strip()[:60] or s[:60]
    return "Partner"


def partner_code(c):
    v = ((c or {}).get("fields") or {}).get("partner_code")
    if v in (None, ""):
        return ""
    try:
        return "P%d" % int(float(v))
    except (TypeError, ValueError):
        return "P" + str(v).strip()


def partner_type(c):
    kinds = [t[8:].replace("-", " ") for t in (c or {}).get("tags") or []
             if t.startswith("partner-") and t != "partner-call-first"]
    return ", ".join(sorted(kinds)) if kinds else ""


def caller_label(c):
    ph = (c or {}).get("phone") or {}
    return "Caller " + ph["last4"] if ph.get("last4") else "Caller (no number)"


def label(c, kind, deal=None):
    if kind == "partner":
        code = partner_code(c)
        return (place(c, deal) + (" " + code if code else "")).strip()
    if kind == "unknown_caller" or not c.get("named"):
        return caller_label(c)
    name = c.get("first") or ""
    if c.get("last_initial"):
        name += " " + c["last_initial"]
    return (name.strip() or caller_label(c)) + " " + family_code(c["id"])


# ---------------------------------------------------------------- who is who

def stage_of(c):
    return str(((c.get("fields") or {}).get("agent_stage") or "")).strip()


def classify(raw, p):
    """{contact id: {"kind", "why"}} for every contact."""
    internal = raw.get("internal") or {}
    phones, emails = set(internal.get("phones") or []), set(internal.get("emails") or [])
    domains = {d.lower() for d in internal.get("domains") or []}
    alert = set(p.get("internal_contacts") or [])
    partner_deals = {o["contactId"] for o in raw.get("opportunities") or []
                     if raw.get("partner_pipeline_id") and o.get("pipelineId") == raw["partner_pipeline_id"]}
    since = et_date_start(p.get("since"))
    out = {}
    for c in raw.get("contacts") or []:
        cid, tags = c["id"], set(c.get("tags") or [])
        stage = stage_of(c)
        outcome = str((c.get("fields") or {}).get("call_outcome") or "").strip()
        ph, em = c.get("phone") or {}, c.get("email") or {}
        why, kind = "", ""
        if cid in alert:
            kind, why = "internal", "alert or owner contact"
        elif tags & INTERNAL_TAGS:
            kind, why = "internal", "tag " + sorted(tags & INTERNAL_TAGS)[0]
        elif c.get("name_test"):
            kind, why = "internal", "test record"
        elif ph.get("key") and ph["key"] in phones:
            kind, why = "internal", "a phone of the home or its staff"
        elif em.get("key") and em["key"] in emails:
            kind, why = "internal", "an email of the home or its staff"
        elif em.get("domain") and em["domain"] in domains:
            kind, why = "internal", "Surven or home email domain"
        elif "referral-partner" in tags or any(t.startswith("partner-") for t in tags):
            kind, why = "partner", "partner tag"
        elif cid in partner_deals:
            kind, why = "partner", "deal in the partner pipeline"
        elif re.match(r"^partner\s*:", stage, re.I):
            kind, why = "partner", "Agent Stage partner"
        elif re.match(r"^not a family\b", stage, re.I):
            kind, why = "not_family", stage[:60]
        elif outcome in ("Not Qualified", "Wrong Number"):
            kind, why = "not_family", "call outcome " + outcome
        elif "job-seeker" in tags:
            kind, why = "not_family", "tag job-seeker"
        elif since and (ts(c.get("added")) or since) < since:
            kind, why = "before_start", "added before " + p.get("since", "")
        elif not c.get("named") and stage.lower() in ("", "new"):
            kind, why = "unknown_caller", "no name, not judged yet"
        else:
            kind, why = "family", "real family"
        out[cid] = {"kind": kind, "why": why}
    return out


def ids_of(cls, *kinds):
    return {cid for cid, v in cls.items() if v["kind"] in kinds}


# ---------------------------------------------------------------- messages

def by_contact(raw):
    out = {}
    for m in raw.get("messages") or []:
        if m.get("cid"):
            out.setdefault(m["cid"], []).append(m)
    for v in out.values():
        v.sort(key=lambda m: str(m.get("when") or ""))
    return out


def sent(m):
    return m.get("dir") == "outbound" and (m.get("status") or "") not in NOT_SENT


def is_call(m):
    return m.get("type") in CALL_TYPES


def placed(m):
    """An outbound call that actually rang: not a workflow call GoHighLevel cancelled or failed to start."""
    return is_call(m) and m.get("dir") == "outbound" and (m.get("cst") or m.get("status") or "") not in NOT_PLACED


def open_beds_send(m):
    """Our weekly open rooms email (a bulk send, matched by subject)."""
    return m.get("type") in EMAIL_TYPES and m.get("dir") == "outbound" and bool(OPEN_BEDS_SUBJECT.search(m.get("subj") or ""))


def talk(m):
    """A completed call of 60 seconds or more, either way (the OS rule for 'reached')."""
    return is_call(m) and (m.get("cst") or m.get("status")) == "completed" and isinstance(m.get("dur"), (int, float)) \
        and m["dur"] >= TALK_SECONDS


def human_out(m):
    """A touch from Surven that counts as an answer: an outbound call that rang (the speed-to-lead call rings Joey
    and bridges the family), or a text or email that was sent and not by an automatic workflow or the weekly bulk
    open rooms email."""
    if m.get("dir") != "outbound":
        return False
    if is_call(m):
        return placed(m)
    return (m.get("type") in TEXT_TYPES | EMAIL_TYPES and sent(m) and m.get("src") != "workflow"
            and not open_beds_send(m))


def first_contact(msgs, start):
    """Earliest outbound call, hand-sent text or email, or 60s+ inbound talk at or after start."""
    floor = start - dt.timedelta(minutes=1)
    for m in msgs:
        t = ts(m.get("when"))
        if t is None or t < floor:
            continue
        if human_out(m) or (m.get("dir") == "inbound" and talk(m)):
            return t
    return None


def first_inbound(c, msgs):
    cands = [ts(c.get("added"))]
    cands += [ts(m.get("when")) for m in msgs if m.get("dir") == "inbound"][:1]
    cands = [x for x in cands if x]
    return min(cands) if cands else None


def median(values):
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def reached(msgs, start=None, end=None):
    """Talked with: a 60s+ call either way, or a two-way text or email. With a window, the talk (or the reply
    plus our answer) has to fall inside it."""
    def ok(m):
        return start is None or inside(m.get("when"), start, end)
    if any(talk(m) and ok(m) for m in msgs):
        return True
    for kinds in (TEXT_TYPES, EMAIL_TYPES):
        ins = [m for m in msgs if m.get("type") in kinds and m.get("dir") == "inbound" and ok(m)]
        outs = [m for m in msgs if m.get("type") in kinds and sent(m) and ok(m)]
        if ins and outs:
            return True
    return False


def how_came(c, msgs):
    tags, src = set(c.get("tags") or []), (c.get("source") or "").lower()
    if "referred-by-partner" in tags or (c.get("fields") or {}).get("referred_by") or "referral" in src:
        return "referral partner"
    if "website" in src or "form" in src:
        return "website"
    if "chat" in src:
        return "website chat"
    first = next((m for m in msgs if m.get("dir") == "inbound"), None)
    if first is not None:
        if is_call(first):
            return "phone call"
        if first.get("type") in TEXT_TYPES:
            return "text"
        if first.get("type") in EMAIL_TYPES:
            return "email"
    return "other"


# ---------------------------------------------------------------- pipelines

def stage_names(raw, pipeline_id):
    for p in raw.get("pipelines") or []:
        if p["id"] == pipeline_id:
            return [(s["id"], s["name"]) for s in p["stages"]]
    return []


def deals_in(raw, pipeline_id):
    return [o for o in raw.get("opportunities") or [] if pipeline_id and o.get("pipelineId") == pipeline_id]


def partner_deal_by_contact(raw):
    out = {}
    for o in deals_in(raw, raw.get("partner_pipeline_id")):
        prev = out.get(o["contactId"])
        if prev is None or str(o.get("updated") or "") > str(prev.get("updated") or ""):
            out[o["contactId"]] = o
    return out


def partner_stages(raw):
    names = stage_names(raw, raw.get("partner_pipeline_id"))
    deals = deals_in(raw, raw.get("partner_pipeline_id"))
    rows = []
    for sid, name in names:
        here = [o for o in deals if o.get("stageId") == sid]
        rows.append({"id": sid, "name": name, "total": len(here),
                     "open": sum(1 for o in here if o.get("status") == "open"),
                     "lost": sum(1 for o in here if o.get("status") in ("lost", "abandoned")),
                     "won": sum(1 for o in here if o.get("status") == "won")})
    known = {sid for sid, _ in names}
    other = [o for o in deals if o.get("stageId") not in known]
    if other:
        rows.append({"id": "", "name": "Other stage", "total": len(other), "open": 0, "lost": 0, "won": 0})
    return rows, len(deals)


def partner_moves(raw, start, end):
    names = dict(stage_names(raw, raw.get("partner_pipeline_id")))
    deals = deals_in(raw, raw.get("partner_pipeline_id"))
    moved = [o for o in deals if inside(o.get("stage_changed"), start, end)]
    by = {}
    for o in moved:
        n = names.get(o.get("stageId"), "Other stage")
        by[n] = by.get(n, 0) + 1
    last = max((ts(o.get("stage_changed")) for o in deals if ts(o.get("stage_changed"))), default=None)
    return {"moved": len(moved), "by_stage": by, "last_move": last.isoformat() if last else None}


# ---------------------------------------------------------------- tours and move-ins

def tour_rows(raw, cls, p, now):
    contacts = {c["id"]: c for c in raw.get("contacts") or []}
    test = set(p.get("test_events") or [])
    evs = [e for e in raw.get("tour_events") or [] if e.get("id") not in test]
    latest_past = {}
    for e in evs:
        s = ts(e.get("start"))
        if e.get("deleted") or e.get("status") in ("cancelled", "canceled", "invalid") or s is None or s > now:
            continue
        cur = latest_past.get(e.get("contactId"))
        if cur is None or s > ts(cur.get("start")):
            latest_past[e.get("contactId")] = e
    rows = []
    for e in evs:
        cid = e.get("contactId") or ""
        c = contacts.get(cid) or {}
        kind = (cls.get(cid) or {}).get("kind", "unknown")
        s, en = ts(e.get("start")), ts(e.get("end"))
        st = e.get("status") or ""
        res = str((c.get("fields") or {}).get("tour_result") or "").strip()
        tags = set(c.get("tags") or [])
        if e.get("deleted") or st in ("cancelled", "canceled", "invalid"):
            status = "cancelled"
        elif st == "showed":
            status = "held"
        elif st == "noshow":
            status = "no-show"
        elif s is None:
            status = "unlogged"
        elif (en or s) > now:
            status = "booked"
        elif (latest_past.get(cid) or {}).get("id") == e.get("id") and res:
            status = "no-show" if res.lower().startswith("no show") else "held"
        elif (latest_past.get(cid) or {}).get("id") == e.get("id") and tags & HELD_TAGS:
            status = "held"
        elif (latest_past.get(cid) or {}).get("id") == e.get("id") and tags & NOSHOW_TAGS:
            status = "no-show"
        else:
            status = "unlogged"
        rows.append({"id": e.get("id"), "cid": cid, "kind": kind, "counted": kind == "family", "start": e.get("start"),
                     "added": e.get("added"), "status": status})
    return rows


def toured_by_stage(raw, cls):
    """Family deals at Tour Attended or a later stage (open or won): a tour happened even if no calendar event."""
    fam = raw.get("family_pipeline_id")
    names = {sid: n.lower() for sid, n in stage_names(raw, fam)}
    out = {}
    for o in deals_in(raw, fam):
        if (cls.get(o["contactId"]) or {}).get("kind") != "family":
            continue
        if names.get(o.get("stageId"), "") in TOURED_STAGES and o.get("status") in ("open", "won"):
            out[o["contactId"]] = o
        elif o.get("status") == "won":
            out[o["contactId"]] = o
    return out


def tours(raw, cls, p, now, start, end):
    rows = [r for r in tour_rows(raw, cls, p, now) if r["counted"]]
    by_stage = toured_by_stage(raw, cls)
    held_ids = {r["cid"] for r in rows if r["status"] == "held"}
    res_ids = {c["id"] for c in raw.get("contacts") or [] if (cls.get(c["id"]) or {}).get("kind") == "family"
               and str((c.get("fields") or {}).get("tour_result") or "").strip()
               and not str(c["fields"]["tour_result"]).lower().startswith("no show")}
    toured = held_ids | set(by_stage) | res_ids
    stage_week = {cid for cid, o in by_stage.items() if inside(o.get("stage_changed"), start, end)}
    held_week = {r["cid"] for r in rows if r["status"] == "held" and inside(r["start"], start, end)}
    return {
        "booked_week": sum(1 for r in rows if inside(r["added"], start, end) and r["status"] != "cancelled"),
        "held_week": len(held_week | stage_week),
        "held_week_calendar": len(held_week),
        "held_week_stage_only": len(stage_week - held_week),
        "upcoming": sum(1 for r in rows if r["status"] == "booked" and inside(r["start"], now, now + dt.timedelta(days=7))),
        "toured_to_date": len(toured),
        "toured_calendar": len(held_ids),
        "toured_stage_only": len((set(by_stage) | res_ids) - held_ids),
        "no_show_to_date": len({r["cid"] for r in rows if r["status"] == "no-show"}),
        "unlogged": sum(1 for r in rows if r["status"] == "unlogged"),
        "calendar_events": len(rows),
        "not_counted": sum(1 for r in tour_rows(raw, cls, p, now) if not r["counted"]),
    }


def families_deciding(raw, cls):
    """Families who toured or are close and have not decided: deal at Tour Attended, Post-Tour Follow-Up or Move-In
    Pending (open), or the planner's Agent Stage says they are thinking it over."""
    fam = raw.get("family_pipeline_id")
    names = {sid: n.lower() for sid, n in stage_names(raw, fam)}
    out = {o["contactId"] for o in deals_in(raw, fam) if o.get("status") == "open"
           and names.get(o.get("stageId"), "") in TOURED_STAGES and (cls.get(o["contactId"]) or {}).get("kind") == "family"}
    out |= {c["id"] for c in raw.get("contacts") or [] if (cls.get(c["id"]) or {}).get("kind") == "family"
            and "thinking it over" in stage_of(c).lower()}
    return len(out)


def move_ins(raw, cls, start=None, end=None):
    fam = raw.get("family_pipeline_id")
    won = {o["contactId"]: o for o in deals_in(raw, fam) if o.get("status") == "won"
           and (cls.get(o["contactId"]) or {}).get("kind") == "family"}
    staged = {c["id"] for c in raw.get("contacts") or [] if (cls.get(c["id"]) or {}).get("kind") == "family"
              and re.match(r"^(moved in|closed: moved in)", stage_of(c), re.I)}
    total = set(won) | staged
    week = {cid for cid, o in won.items() if start and inside(o.get("status_changed"), start, end)}
    return {"to_date": len(total), "week": len(week), "won_deals": len(won), "planner_says": len(staged - set(won))}


# ---------------------------------------------------------------- activity

def activity(raw, cls, start, end):
    """What Surven did from the location in the window, to anyone who is not internal."""
    internal = ids_of(cls, "internal")
    partners = ids_of(cls, "partner")
    real = ids_of(cls, "family", "partner")
    out = {"calls": 0, "calls_by_hand": 0, "calls_answered": 0, "texts": 0, "texts_by_hand": 0, "emails": 0,
           "people": 0, "partner_calls": 0, "partner_texts": 0, "partner_emails": 0, "inbound": 0}
    people = set()
    for m in raw.get("messages") or []:
        cid = m.get("cid")
        if not cid or cid in internal or not inside(m.get("when"), start, end):
            continue
        is_p = cid in partners
        if m.get("dir") == "inbound":
            out["inbound"] += 1
            if is_call(m) and (m.get("cst") or m.get("status")) == "completed" and cid in real:
                out["calls_answered"] += 1   # families and partners only, never robocalls or job seekers
            continue
        if is_call(m):
            if not placed(m):
                continue                     # a workflow call that never rang is not a call we made
            out["calls"] += 1
            out["calls_by_hand"] += 1 if m.get("type") == "TYPE_CALL" else 0
            out["partner_calls"] += 1 if is_p else 0
            people.add(cid)
        elif m.get("type") in TEXT_TYPES and sent(m):
            out["texts"] += 1
            out["texts_by_hand"] += 1 if m.get("src") != "workflow" else 0
            out["partner_texts"] += 1 if is_p else 0
            people.add(cid)
        elif m.get("type") in EMAIL_TYPES and sent(m):
            out["emails"] += 1
            out["partner_emails"] += 1 if is_p else 0
            people.add(cid)
    out["people"] = len(people)
    return out


def partner_touches(raw, cls, start, end):
    partners = ids_of(cls, "partner")
    touched, replied, n = set(), set(), 0
    for m in raw.get("messages") or []:
        cid = m.get("cid")
        if cid not in partners or not inside(m.get("when"), start, end):
            continue
        if m.get("dir") == "outbound" and (placed(m) if is_call(m) else sent(m)):
            n += 1
            touched.add(cid)
        elif m.get("dir") == "inbound":
            replied.add(cid)
    return {"touches": n, "partners_touched": len(touched), "partners_replied": len(replied)}


def last_touch(msgs):
    """(time, short description) of the newest call, text or email either way, or (None, '')."""
    for m in reversed(msgs):
        t = ts(m.get("when"))
        if t is None:
            continue
        if is_call(m) and m.get("dir") == "outbound" and not placed(m):
            continue                         # never rang: not a touch
        if is_call(m):
            d = m.get("dur")
            how = "call"
            if m.get("dir") == "inbound":
                how = "they called"
            st = m.get("cst") or m.get("status") or ""
            if isinstance(d, (int, float)) and d > 0:
                how += " %d:%02d" % (d // 60, d % 60)
            if st in ("voicemail",):
                how += ", voicemail"
            elif st in ("no-answer", "noanswer", "busy"):
                how += ", no answer"
            return t, how
        if m.get("type") in TEXT_TYPES:
            return t, "they texted" if m.get("dir") == "inbound" else "text"
        if m.get("type") in EMAIL_TYPES:
            return t, "they emailed" if m.get("dir") == "inbound" else "email"
    return None, ""


# ---------------------------------------------------------------- unanswered

def unanswered(raw, cls, now, hours=24):
    """Inbound texts, emails and missed calls with no answer from Surven since, older than `hours`."""
    contacts = {c["id"]: c for c in raw.get("contacts") or []}
    pdeal = partner_deal_by_contact(raw)
    out = []
    for cid, msgs in by_contact(raw).items():
        kind = (cls.get(cid) or {}).get("kind")
        if kind not in ("family", "partner"):
            continue
        pending = None
        for m in msgs:
            if m.get("dir") == "inbound":
                if m.get("type") in TEXT_TYPES | EMAIL_TYPES | CHAT_TYPES:
                    txt = m.get("text") or ""
                    if NO_ANSWER_NEEDED.match(txt) or AUTO_REPLY.search((m.get("subj") or "") + " " + txt[:80]):
                        continue
                    if txt and "?" not in txt and CLOSER.match(txt):
                        continue                 # a polite closer that asks nothing
                    pending = pending or m
                elif is_call(m):
                    if (m.get("cst") or m.get("status")) in MISSED_CALL:
                        pending = pending or m
                    else:
                        pending = None          # we picked up: answered
            elif human_out(m):
                pending = None
        if pending is None:
            continue
        t = ts(pending.get("when"))
        if t is None or (now - t).total_seconds() < hours * 3600:
            continue
        ch = "missed call" if is_call(pending) else ("email" if pending.get("type") in EMAIL_TYPES else "text")
        c = contacts.get(cid) or {"id": cid}
        out.append({"cid": cid, "kind": kind, "label": label(c, kind, pdeal.get(cid)), "channel": ch,
                    "when": pending.get("when"), "age_days": round((now - t).total_seconds() / 86400.0, 1),
                    "preview": (pending.get("subj") or pending.get("text") or "")[:120], "conv": pending.get("conv")})
    out.sort(key=lambda x: -x["age_days"])
    return out


# ---------------------------------------------------------------- one call for everything

def families_block(raw, cls, now, start, end):
    contacts = {c["id"]: c for c in raw.get("contacts") or []}
    msgs = by_contact(raw)
    fams = [contacts[cid] for cid in ids_of(cls, "family") if cid in contacts]
    new = [c for c in fams if inside(c.get("added"), start, end)]
    month_start = now - dt.timedelta(days=30)
    speeds_week, speeds_month, came = [], [], {}
    for c in fams:
        mm = msgs.get(c["id"], [])
        t0 = first_inbound(c, mm)
        if t0 is None or t0 < month_start:
            continue
        t1 = first_contact(mm, t0)
        mins = round((t1 - t0).total_seconds() / 60.0, 1) if t1 else None
        if mins is not None:
            speeds_month.append(mins)
            if start <= t0 < end:
                speeds_week.append(mins)
    for c in new:
        k = how_came(c, msgs.get(c["id"], []))
        came[k] = came.get(k, 0) + 1
    reached_week = sum(1 for c in fams if reached(msgs.get(c["id"], []), start, end))
    new_reached = sum(1 for c in new if reached(msgs.get(c["id"], [])))
    new_no_touch = sum(1 for c in new if first_contact(msgs.get(c["id"], []), first_inbound(c, msgs.get(c["id"], []))
                                                       or now) is None)
    return {
        "total": len(fams), "new_week": len(new), "new_by_way": came,
        "reached_week": reached_week, "new_reached": new_reached, "new_no_touch": new_no_touch,
        "speed_week_min": median(speeds_week), "speed_week_n": len(speeds_week),
        "speed_month_min": median(speeds_month), "speed_month_n": len(speeds_month),
        "unknown_callers": len(ids_of(cls, "unknown_caller")),
        "unknown_callers_week": sum(1 for cid in ids_of(cls, "unknown_caller")
                                    if inside((contacts.get(cid) or {}).get("added"), start, end)),
    }


def partners_block(raw, cls, p, now, start, end):
    if not raw.get("partner_pipeline_id"):
        return None
    rows, total = partner_stages(raw)
    by = {r["name"].lower(): r for r in rows}
    on_list = sum(by.get(n, {}).get("open", 0) for n in PARTNER_ON_LIST)
    referral_families = sum(1 for c in raw.get("contacts") or [] if (cls.get(c["id"]) or {}).get("kind") == "family"
                            and ("referred-by-partner" in (c.get("tags") or [])
                                 or (c.get("fields") or {}).get("referred_by")))
    goal = p.get("partner_goal") or {}
    return {
        "stages": rows, "total": total, "on_weekly_list": on_list,
        "yes_partner": by.get("yes partner", {}).get("open", 0),
        "sent_referral": by.get("sent a referral", {}).get("open", 0),
        "families_from_partners": referral_families,
        "moves": partner_moves(raw, start, end),
        "touches": partner_touches(raw, cls, start, end),
        "goal": goal,
        "open_beds_last": raw.get("open_beds_last"),
    }


def build(raw, p, now, mode):
    """Every number on the page and in the report, from one raw pull."""
    cls = classify(raw, p)
    start, end = window(now, 7)
    counts = {}
    for v in cls.values():
        counts[v["kind"]] = counts.get(v["kind"], 0) + 1
    goal = p.get("goal") or {}
    gstart = et_date_start(goal.get("start")) if goal.get("start") else None
    mi = move_ins(raw, cls, start, end)
    tr = tours(raw, cls, p, now, start, end)
    by = et_date_start(goal.get("by")) if goal.get("by") else None
    return {
        "client": p["key"], "label": raw.get("location", {}).get("name") or p["label"], "short": p["short"],
        "city": raw.get("location", {}).get("city") or "", "mode": mode, "now": now.isoformat(),
        "week": {"start": start.isoformat(), "end": end.isoformat()},
        "kinds": counts,
        "families": families_block(raw, cls, now, start, end),
        "tours": tr,
        "move_ins": mi,
        "deciding": families_deciding(raw, cls),
        "goal": {"move_ins": goal.get("move_ins"), "tours": goal.get("tours"), "by": goal.get("by"),
                 "start": goal.get("start"), "days_left": (by - now).days if by else None,
                 "since_start": bool(gstart)},
        "partners": partners_block(raw, cls, p, now, start, end),
        "activity": activity(raw, cls, start, end),
        "unanswered": unanswered(raw, cls, now),
        "discovery": raw.get("discovery") or {},
        "errors": raw.get("errors") or [],
    }, cls
