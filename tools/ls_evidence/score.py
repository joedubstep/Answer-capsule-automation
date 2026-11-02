"""Turn the raw pull into the Lead Suite evidence: every lead's 6 scored boxes, every booked call's 5 boxes, the SOP
rate, the refund scoreboard, and which rows still need typing into the portal. Pure functions; the CLI only reads
and writes JSON.

  python3 -m tools.ls_evidence.score [--raw /tmp/ls_evidence/raw.json] [--out /tmp/ls_evidence/evidence.json]
                                     [--prev <last page>] [--entered-through 2026-11-01] [--now 2026-11-08T11:00:00Z]

Each box is Yes, No, Not due or Unknown, with the time stamp that proves it. An STL field in GHL wins when it is
filled; the message time stamps fill it when it is blank, and flag it when they disagree.

Lead boxes (portal order): 1 triple dial within 3 to 5 min of the form fill, 2 SMS 1 within 5 min, 3 double dial right
after a reply, 4 SMS 2 at plus 3 to 4 hours, 5 SMS 3 at plus 2 to 3 hours after SMS 2, 6 lead replied.
Call boxes (portal order): 1 triage call before the main call, 2 show-rate SOP followed, 3 pre-call video email the
evening before, 4 morning confirm call or text, 5 showed.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

from shared import et
from tools.ls_evidence import profile as prof

UTC = dt.timezone.utc
YES, NO, NOT_DUE, UNKNOWN = "Yes", "No", "Not due", "Unknown"
CHAR = {YES: "Y", NO: "N", NOT_DUE: "-", UNKNOWN: "?"}
LEAD_BOXES = [
    ("triple_dial", "Triple dial within 3 to 5 min of the form fill"),
    ("sms1", "SMS 1 within 5 min"),
    ("double_dial", "Double dial right after a reply"),
    ("sms2", "SMS 2 at 3 to 4 hours"),
    ("sms3", "SMS 3 at 2 to 3 hours after SMS 2"),
    ("lead_replied", "Lead replied"),
]
CALL_BOXES = [
    ("triage", "Triage call before the main call"),
    ("show_sop", "Show-rate SOP followed"),
    ("precall_email", "Pre-call video email the evening before"),
    ("morning_confirm", "Morning confirm call or text"),
    ("showed", "Showed"),
]
SOP_LEAD = ("triple_dial", "sms1", "double_dial", "sms2", "sms3")      # "lead replied" is an outcome, not the SOP
SOP_CALL = ("triage", "show_sop", "precall_email", "morning_confirm")  # "showed" is an outcome, not the SOP
LEAD_FIELD = {"triple_dial": "triple_dial", "sms1": "sms1", "double_dial": "double_dial", "sms2": "sms2",
              "sms3": "sms3", "lead_replied": "lead_replied"}
FIELD_LABEL = {"triple_dial": "STL Triple Dial Done", "sms1": "STL SMS 1", "double_dial": "STL Double Dial After Reply",
               "sms2": "STL SMS 2", "sms3": "STL SMS 3", "lead_replied": "STL Lead Replied",
               "triage": "STL Triage Call Done", "precall_email": "STL Pre-call Email",
               "morning_confirm": "STL Morning Confirm Done", "showed": "STL Showed"}
CALL_FIELD = {"triage": "triage", "precall_email": "precall_email", "morning_confirm": "morning_confirm",
              "showed": "showed"}

CALL_TYPES = {"TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_IVR_CALL"}
CHAT_TYPES = {"TYPE_LIVE_CHAT", "TYPE_WEBCHAT", "TYPE_FACEBOOK", "TYPE_INSTAGRAM", "TYPE_WHATSAPP", "TYPE_GMB"}
EXCLUDE_TAGS = {"svn-test", "svn-tooltest", "test-contact-delete-me", "owner-joey"}
SHOWED_STATUS = {"showed", "show", "completed"}
NOSHOW_STATUS = {"noshow", "no_show", "no-show"}
CANCELLED_STATUS = {"cancelled", "canceled", "invalid"}
NOSHOW_STAGES = {"no show"}
AFTER_CALL_STAGES = {"follow up", "closed", "closed won", "won", "client", "proposal"}
NOSHOW_NOTE_RX = re.compile(r"no.?show|didn'?t show|did not show|never showed|stood (me |us )?up", re.I)
OUTCOME_NOTE_RX = re.compile(r"^\s*outcome\s*:", re.I)
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE_RX = re.compile(r"(\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
OUT_DIR = prof.OUT_DIR

# US zones: (standard offset, observes daylight time). Daylight time switches on the Eastern rule in shared.et for every
# zone (no tzdata needed), so on the two switch nights a non-Eastern lead's clock can be off by an hour for an hour.
ZONES = {"eastern": (-5, True), "central": (-6, True), "mountain": (-7, True), "arizona": (-7, False),
         "pacific": (-8, True), "alaska": (-9, True), "hawaii": (-10, False)}
ZONE_RX = [
    ("arizona", r"phoenix|arizona"),
    ("hawaii", r"honolulu|hawaii|\bhst\b"),
    ("alaska", r"anchorage|juneau|alaska|\bakst\b|\bakdt\b"),
    ("pacific", r"los_angeles|pacific|vancouver|\bpst\b|\bpdt\b|tijuana"),
    ("mountain", r"denver|boise|mountain|edmonton|\bmst\b|\bmdt\b"),
    ("central", r"chicago|central|winnipeg|menominee|north_dakota|indiana/(knox|tell_city)|\bcst\b|\bcdt\b"),
    ("eastern", r"new_york|detroit|indiana|kentucky|toronto|eastern|\best\b|\bedt\b"),
]
ZONE_LABEL = {"eastern": "Eastern", "central": "Central", "mountain": "Mountain", "arizona": "Arizona",
              "pacific": "Pacific", "alaska": "Alaska", "hawaii": "Hawaii"}


# ---------------------------------------------------------------- small helpers

def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def scrub(s):
    """No phone numbers or email addresses on the page."""
    return PHONE_RX.sub("[phone]", EMAIL_RX.sub("[email]", str(s or "")))


def short_hash(location_id, record_id):
    return hashlib.sha256(f"{location_id}:{record_id}".encode()).hexdigest()[:12]


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def flat(v):
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v)


def code_str(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return flat(v).strip()


def yes_no(v):
    """True, False or None from a GHL yes/no style value ("Yes", ["Yes"], "true", 1, "No")."""
    s = norm(flat(v))
    if not s:
        return None
    if s in ("yes", "y", "true", "1", "done", "sent", "x", "checked", "on", "completed") or s.startswith("yes"):
        return True
    if s in ("no", "n", "false", "0", "not done", "none", "off", "not sent") or s.startswith("no "):
        return False
    return None


def field_time(v):
    """A time stamp from a GHL field, or None when it holds no time of day (a date only)."""
    if v in (None, "", []):
        return None
    if isinstance(v, str) and re.match(r"^\s*\d{4}-\d{2}-\d{2}\s*$", v):
        return None
    d = et.parse(v)
    if d is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
        if d.hour == 0 and d.minute == 0 and d.second == 0:
            return None        # a DATE field stores midnight UTC: no time of day
    return d


def hm(s, default):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(s or ""))
    return (int(m.group(1)), int(m.group(2))) if m else default


def clock(d):
    h = d.hour % 12 or 12
    return f"{h}{'' if d.minute == 0 else ':%02d' % d.minute}{'am' if d.hour < 12 else 'pm'}"


def fmt_et(ts):
    d = ts if isinstance(ts, dt.datetime) else et.parse(ts)
    if d is None:
        return ""
    d = et.to_et(d)
    return d.strftime("%a %b ") + str(d.day) + ", " + clock(d)


def fmt_day(d):
    return d.strftime("%a %b ") + str(d.day)


def gap(a, b):
    """Plain length of time from a to b: '3 min', '2 h 10 min', '3 days'."""
    mins = int(round((b - a).total_seconds() / 60.0))
    if mins < 0:
        return "before it"
    if mins < 60:
        return plural(mins, "min", "min")
    if mins < 48 * 60:
        h, m = divmod(mins, 60)
        return f"{h} h" + (f" {m} min" if m else "")
    return plural(mins // 1440, "day")


# ---------------------------------------------------------------- time zones (lead's own clock)

def zone_of(tz_text):
    s = str(tz_text or "").lower()
    for key, rx in ZONE_RX:
        if re.search(rx, s):
            return key
    return "eastern"


def _dst(utc_dt):
    return et.et_offset_hours(utc_dt) == -4


def offset_hours(zone, utc_dt):
    base, dst = ZONES.get(zone, ZONES["eastern"])
    return base + (1 if dst and _dst(utc_dt) else 0)


def local(utc_dt, zone):
    """Naive wall time in the zone."""
    return (utc_dt.astimezone(UTC) + dt.timedelta(hours=offset_hours(zone, utc_dt))).replace(tzinfo=None)


def to_utc(naive_local, zone):
    base, _ = ZONES.get(zone, ZONES["eastern"])
    guess = (naive_local - dt.timedelta(hours=base)).replace(tzinfo=UTC)
    return (naive_local - dt.timedelta(hours=offset_hours(zone, guess))).replace(tzinfo=UTC)


def in_quiet(utc_dt, zone, sop):
    q = sop.get("quiet_hours") or {}
    f, t = hm(q.get("from"), (20, 45)), hm(q.get("to"), (8, 0))
    lt = local(utc_dt, zone)
    cur = (lt.hour, lt.minute)
    return cur >= f or cur < t if f > t else f <= cur < t


def out_of_quiet(utc_dt, zone, sop):
    """The same moment if it is inside contact hours, else the next morning's opening time (lead's clock)."""
    if not in_quiet(utc_dt, zone, sop):
        return utc_dt, False
    t = hm((sop.get("quiet_hours") or {}).get("to"), (8, 0))
    lt = local(utc_dt, zone)
    day = lt.date() if (lt.hour, lt.minute) < t else lt.date() + dt.timedelta(days=1)
    return to_utc(dt.datetime(day.year, day.month, day.day, t[0], t[1]), zone), True


def window(start, length, zone, sop):
    """(window start, window end), moved past quiet hours when the start falls inside them."""
    s, moved = out_of_quiet(start, zone, sop)
    return s, s + length, moved


# ---------------------------------------------------------------- settings and the 90-day clock

def live_date(settings):
    return dt.date.fromisoformat(str((settings.get("ads") or {}).get("live_date") or "2026-08-08"))


def live_start_utc(settings):
    d = live_date(settings)
    return et.et_to_utc(dt.datetime(d.year, d.month, d.day))


def pause_ranges(settings):
    out = []
    for p in (settings.get("ads") or {}).get("pauses") or []:
        if p.get("burns_clock") is False:
            out.append((dt.date.fromisoformat(p["from"]), dt.date.fromisoformat(p["to"])))
    return out


def clock_window(settings, today):
    """The 90-day window: live date, end date (paused days skipped), days used and left as of `today` (ET date)."""
    c = settings.get("contract") or {}
    days = int(c.get("window_days") or 90)
    live = live_date(settings)
    pauses = pause_ranges(settings)

    def paused(d):
        return any(a <= d <= b for a, b in pauses)

    d, n, skipped = live, 0, 0
    while True:
        if paused(d):
            skipped += 1
        else:
            n += 1
            if n == days:
                break
        d += dt.timedelta(days=1)
    end = d
    used = 0
    if today >= live:
        x = live
        last = min(today, end)
        while x <= last:
            if not paused(x):
                used += 1
            x += dt.timedelta(days=1)
    return {"live": live.isoformat(), "end": end.isoformat(), "days": days, "used": used, "left": days - used,
            "paused_days": skipped, "over": today > end, "started": today >= live,
            "pauses": [[a.isoformat(), b.isoformat()] for a, b in pauses],
            "end_utc": et.et_to_utc(dt.datetime(end.year, end.month, end.day) + dt.timedelta(days=1)).isoformat()}


# ---------------------------------------------------------------- one lead's facts

def lead_in(lead, live):
    """(lead-in time, where it came from). The STL Lead In At field wins when it holds a time of day."""
    t = field_time((lead.get("fields") or {}).get("lead_in_at"))
    if t:
        return t, "STL Lead In At"
    added = et.parse(lead.get("dateAdded"))
    floor = live - dt.timedelta(days=1)
    if added and added >= floor:
        return added, "contact created"
    later = sorted(x for x in (et.parse(o.get("createdAt")) for o in lead.get("opps") or []) if x and x >= floor)
    if later:
        return later[0], "deal created (came back through the form)"
    return added, "contact created"


def is_excluded(lead, joey_contact=None):
    tags = {norm(t) for t in lead.get("tags") or []}
    if lead.get("id") and lead.get("id") == joey_contact:
        return "Joey's own contact"
    if tags & EXCLUDE_TAGS:
        return "test tag"
    v = norm(flat((lead.get("fields") or {}).get("test")))
    if v and v not in ("no", "false", "0", "off", "n"):
        return "test contact"
    if lead.get("test_name"):
        return "test name"
    return ""


def norm_msgs(block, details, sop):
    """Messages as events with a kind: dial, dial_dead, call_in, sms_out, sms_dead, sms_in, email_out, email_in."""
    dead_dial = {norm(x) for x in sop.get("dial_statuses_not_counted") or ["canceled", "cancelled"]}
    dead_sms = {norm(x) for x in sop.get("sms_statuses_not_counted") or ["failed", "undelivered"]}
    wps = float(sop.get("words_per_second") or 1.8)
    talk_min = int(sop.get("talk_min_seconds") or 30)
    out = []
    for m in (block or {}).get("msgs") or []:
        t = et.parse(m.get("when"))
        if t is None:
            continue
        typ, d, st = m.get("type") or "", m.get("dir"), norm(m.get("status"))
        e = {"id": m.get("id"), "t": t, "status": st}
        if typ in CALL_TYPES:
            secs = m.get("duration")
            det = (details or {}).get(m.get("id")) or {}
            if secs in (None, 0) and det.get("duration"):
                secs = det["duration"]
            if secs in (None, 0) and det.get("words"):
                secs = int(round(det["words"] / wps))
            if secs == 0 and st == "completed":
                secs = None
            e["secs"] = secs
            e["talk"] = st == "completed" and (secs is None or secs >= talk_min)
            e["kind"] = ("dial_dead" if st in dead_dial else "dial") if d == "outbound" else "call_in"
        elif typ == "TYPE_SMS" and d == "outbound":
            e["kind"] = "sms_dead" if st in dead_sms else "sms_out"
        elif typ in ("TYPE_SMS", "TYPE_SMS_REACTION") and d == "inbound":
            e["kind"] = "auto_in" if m.get("auto") else "sms_in"
        elif typ == "TYPE_EMAIL" and d == "outbound":
            e["kind"] = "email_out"
            e["subject"] = m.get("subject")
        elif typ == "TYPE_EMAIL" and d == "inbound":
            e["kind"] = "auto_in" if m.get("auto") else "email_in"
        elif typ in CHAT_TYPES and d == "inbound":
            e["kind"] = "msg_in"
        else:
            continue
        out.append(e)
    out.sort(key=lambda x: x["t"])
    return out


def first(ms, kinds, start=None, end=None, skip=()):
    for m in ms:
        if m["kind"] in kinds and (start is None or m["t"] >= start) and (end is None or m["t"] <= end) \
                and m["id"] not in skip:
            return m
    return None


def first_reach(ms, t0):
    """The lead's first reply: a text, email or chat in, a call in, or a call of ours they picked up."""
    floor = t0 - dt.timedelta(minutes=1)
    for m in ms:
        if m["t"] < floor:
            continue
        if m["kind"] in ("sms_in", "email_in", "msg_in"):
            how = {"sms_in": "text", "email_in": "email", "msg_in": "message"}[m["kind"]]
            return {"t": m["t"], "how": how, "talked": False}
        if m["kind"] == "call_in":
            return {"t": m["t"], "how": "call to us" + ("" if m["status"] == "completed" else " (missed)"),
                    "talked": m["status"] == "completed"}
        if m["kind"] == "dial" and m.get("talk"):
            return {"t": m["t"], "how": "picked up our call", "talked": True}
    return None


def box(a, why, t=None, pending=False, src="messages", check=None):
    return {"a": a, "why": why, "t": t.isoformat() if isinstance(t, dt.datetime) else t, "pending": pending,
            "src": src, "check": check}


def apply_field(b, value, label):
    """An STL field that holds Yes or No wins; disagreeing messages become a check note."""
    v = yes_no(value)
    if v is None:
        return b
    a = YES if v else NO
    check = None
    if b["a"] in (YES, NO) and b["a"] != a:
        check = f"GHL field says {a}, the messages say {b['a']}: {b['why']}"
    return {"a": a, "why": f"{label} field: {a}" + (f". Messages: {b['why']}" if b["why"] and not check else ""),
            "t": b["t"], "pending": False, "src": "field", "check": check}


# ---------------------------------------------------------------- the 6 lead boxes

def lead_boxes(t0, zone, ms, sop, now, fields=None, msgs_ok=True, early_missing=False):
    fields = fields or {}
    grace = dt.timedelta(minutes=int(sop.get("grace_minutes") or 0))
    floor = t0 - dt.timedelta(minutes=1)
    start, after_hours = out_of_quiet(t0, zone, sop)
    note = f" (came in after hours, so the clock started {fmt_et(start)} ET)" if after_hours else ""
    reach = first_reach(ms, t0)
    out = {}

    # 1. triple dial
    need = int(sop.get("dials_for_triple") or 3)
    w_end = start + dt.timedelta(minutes=int(sop.get("triple_dial_minutes") or 5)) + grace
    dials = [m for m in ms if m["kind"] == "dial" and floor <= m["t"] <= w_end]
    talked = next((i for i, m in enumerate(dials) if m.get("talk")), None)
    if early_missing:
        b = box(UNKNOWN, "older messages were not read (too many messages)")
    elif len(dials) >= need:
        b = box(YES, f"{need} dials by {clock(et.to_et(dials[need - 1]['t']))}, "
                     f"{gap(start, dials[need - 1]['t'])} after the form{note}", dials[need - 1]["t"])
    elif talked is not None:
        b = box(YES, f"dial {talked + 1} was answered at {clock(et.to_et(dials[talked]['t']))}{note}", dials[talked]["t"])
    elif reach and reach["talked"] and reach["how"].startswith("call to us") and reach["t"] <= w_end:
        b = box(NOT_DUE, f"they called us first, at {fmt_et(reach['t'])}", reach["t"])
    elif now < w_end:
        b = box(NOT_DUE, f"due by {fmt_et(w_end)}", pending=True)
    elif not msgs_ok:
        b = box(UNKNOWN, "messages could not be read")
    else:
        f1 = first(ms, {"dial"}, floor)
        bit = f"first dial {gap(start, f1['t'])} after the form" if f1 else "no dial found"
        b = box(NO, f"{plural(len(dials), 'dial')} in the first {int(sop.get('triple_dial_minutes') or 5)} min; {bit}{note}",
                f1["t"] if f1 else None)
    out["triple_dial"] = b

    # 2. SMS 1
    w_end = start + dt.timedelta(minutes=int(sop.get("sms1_minutes") or 5)) + grace
    s1 = first(ms, {"sms_out"}, floor, w_end)
    if early_missing:
        b = box(UNKNOWN, "older messages were not read (too many messages)")
    elif s1:
        b = box(YES, f"text at {clock(et.to_et(s1['t']))}, {gap(start, s1['t'])} after the form{note}", s1["t"])
    elif reach and reach["talked"] and reach["t"] <= w_end:
        b = box(NOT_DUE, f"they talked with us first, at {fmt_et(reach['t'])}", reach["t"])
    elif now < w_end:
        b = box(NOT_DUE, f"due by {fmt_et(w_end)}", pending=True)
    elif not msgs_ok:
        b = box(UNKNOWN, "messages could not be read")
    else:
        f1 = first(ms, {"sms_out"}, floor)
        b = box(NO, (f"first text {gap(start, f1['t'])} after the form" if f1 else "no text found") + note,
                f1["t"] if f1 else None)
    out["sms1"] = b
    sms1_id = s1["id"] if s1 else None

    # 3. double dial right after a reply
    if not reach:
        b = box(NOT_DUE, "no reply yet")
    elif reach["talked"]:
        b = box(NOT_DUE, f"they talked with us at {fmt_et(reach['t'])} ({reach['how']}), so no double dial was needed",
                reach["t"])
    else:
        r0, moved = out_of_quiet(reach["t"], zone, sop)
        w_end = r0 + dt.timedelta(minutes=int(sop.get("double_dial_minutes") or 10)) + grace
        nd = int(sop.get("dials_for_double") or 2)
        dd = [m for m in ms if m["kind"] == "dial" and reach["t"] <= m["t"] <= w_end]
        ans = next((m for m in dd if m.get("talk")), None)
        when = f"the {reach['how']} at {fmt_et(reach['t'])}" + (" (after hours)" if moved else "")
        if len(dd) >= nd:
            b = box(YES, f"{nd} dials within {gap(reach['t'], dd[nd - 1]['t'])} of {when}", dd[nd - 1]["t"])
        elif ans:
            b = box(YES, f"called back and they picked up, {gap(reach['t'], ans['t'])} after {when}", ans["t"])
        elif now < w_end:
            b = box(NOT_DUE, f"due by {fmt_et(w_end)}", pending=True)
        elif not msgs_ok:
            b = box(UNKNOWN, "messages could not be read")
        else:
            f1 = first(ms, {"dial"}, reach["t"])
            b = box(NO, f"{plural(len(dd), 'dial')} in the {int(sop.get('double_dial_minutes') or 10)} min after {when}"
                        + (f"; next dial {gap(reach['t'], f1['t'])} later" if f1 else "; no dial after it"),
                    f1["t"] if f1 else None)
    out["double_dial"] = b

    # 4. SMS 2 at plus 3 to 4 hours (only while there is no reply)
    h2 = sop.get("sms2_hours") or [3, 4]
    ws2, we2, moved2 = window(start + dt.timedelta(hours=h2[0]), dt.timedelta(hours=h2[1] - h2[0]), zone, sop)
    s2 = None
    span = f"{fmt_et(ws2)} to {clock(et.to_et(we2))}" + (" (moved past quiet hours)" if moved2 else "")
    if reach and reach["t"] < ws2:
        b = box(NOT_DUE, f"they replied ({reach['how']}) at {fmt_et(reach['t'])}, so the texts stop", reach["t"])
    else:
        s2 = first(ms, {"sms_out"}, ws2, we2 + grace, skip={sms1_id})
        if s2:
            b = box(YES, f"text at {fmt_et(s2['t'])}, {gap(start, s2['t'])} after the form", s2["t"])
        elif now < we2 + grace:
            b = box(NOT_DUE, f"due {span}", pending=True)
        elif not msgs_ok:
            b = box(UNKNOWN, "messages could not be read")
        else:
            nx = first(ms, {"sms_out"}, ws2, skip={sms1_id})
            b = box(NO, f"no text {span}" + (f"; next text {fmt_et(nx['t'])}" if nx else ""), nx["t"] if nx else None)
    out["sms2"] = b

    # 5. SMS 3 at plus 2 to 3 hours after SMS 2 (only while there is no reply)
    h3 = sop.get("sms3_hours_after_sms2") or [2, 3]
    anchor = s2["t"] if s2 else ws2
    ws3, we3, moved3 = window(anchor + dt.timedelta(hours=h3[0]), dt.timedelta(hours=h3[1] - h3[0]), zone, sop)
    span = f"{fmt_et(ws3)} to {clock(et.to_et(we3))}" + (" (moved past quiet hours)" if moved3 else "")
    if reach and reach["t"] < ws3:
        b = box(NOT_DUE, f"they replied ({reach['how']}) at {fmt_et(reach['t'])}, so the texts stop", reach["t"])
    else:
        s3 = first(ms, {"sms_out"}, ws3, we3 + grace, skip={sms1_id, s2["id"] if s2 else None})
        if s3:
            b = box(YES, f"text at {fmt_et(s3['t'])}, {gap(anchor, s3['t'])} after SMS 2" + ("" if s2 else " was due"),
                    s3["t"])
        elif now < we3 + grace:
            b = box(NOT_DUE, f"due {span}", pending=True)
        elif not msgs_ok:
            b = box(UNKNOWN, "messages could not be read")
        else:
            nx = first(ms, {"sms_out"}, ws3, skip={sms1_id, s2["id"] if s2 else None})
            b = box(NO, f"no text {span}" + (f"; next text {fmt_et(nx['t'])}" if nx else ""), nx["t"] if nx else None)
    out["sms3"] = b

    # 6. lead replied
    if reach:
        b = box(YES, f"{reach['how']} at {fmt_et(reach['t'])}, {gap(t0, reach['t'])} after the form", reach["t"])
    elif not msgs_ok:
        b = box(UNKNOWN, "messages could not be read")
    else:
        b = box(NO, "no reply so far")
    out["lead_replied"] = b

    for key, role in LEAD_FIELD.items():
        if role in fields:
            out[key] = apply_field(out[key], fields[role], FIELD_LABEL[key])
    return out, {"start": start.isoformat(), "after_hours": after_hours, "reach": reach["t"].isoformat() if reach else None}


# ---------------------------------------------------------------- calls

def merge_calls(events, leads, s_calls):
    """Sales calls per lead: Discovery Call bookings plus Lead Suite calendar copies titled discovery that are not a
    copy of a Discovery Call booking. Client calls never count. Returns rows with a status: booked, cancelled, moved."""
    merge = dt.timedelta(minutes=int(s_calls.get("merge_minutes") or 30))
    rebook = dt.timedelta(minutes=int(s_calls.get("rebook_minutes") or 60))
    keep = []
    for e in events:
        if e.get("deleted") or e.get("contactId") not in leads or e.get("title_kind") == "client":
            continue
        if e.get("cal") == "lead_suite" and e.get("title_kind") != "discovery":
            continue
        start = et.parse(e.get("start"))
        if not start:
            continue
        keep.append(dict(e, _start=start, _booked=et.parse(e.get("booked_at")) or start))
    disc = [e for e in keep if e["cal"] == "discovery"]
    rows, seen = [], set()
    for e in sorted(keep, key=lambda x: (x["cal"] != "discovery", x["_booked"])):
        if e["cal"] != "discovery" and any(d["contactId"] == e["contactId"] and abs(d["_start"] - e["_start"]) <= merge
                                           for d in disc):
            continue
        slot = (e["contactId"], e["_start"], e["status"] in CANCELLED_STATUS)
        if slot in seen:
            continue
        seen.add(slot)
        rows.append(e)
    by_contact = {}
    for e in rows:
        by_contact.setdefault(e["contactId"], []).append(e)
    for cid, lst in by_contact.items():
        lst.sort(key=lambda x: x["_booked"])
        for e in lst:
            if e["status"] not in CANCELLED_STATUS:
                e["_state"] = "booked"
                continue
            later = [x for x in lst if x is not e and x["status"] not in CANCELLED_STATUS
                     and x["_booked"] >= e["_booked"] - rebook]
            e["_state"] = "moved" if later else "cancelled"
    return sorted(rows, key=lambda x: x["_start"])


def note_after(notes, start, hours=72):
    best = None
    for n in notes or []:
        t = et.parse(n.get("when"))
        if t and start - dt.timedelta(hours=2) <= t <= start + dt.timedelta(hours=hours) and n.get("text"):
            if best is None or t < best[0]:
                best = (t, n["text"])
    return best


def sentences(text, n=5, limit=600):
    text = re.sub(r"\s+", " ", scrub(text)).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:n]).strip()
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + "..."


def call_boxes(call, t0, zone, ms, sop, now, notes=None, fields=None, stage="", latest=False, msgs_ok=True):
    """The 5 boxes for one booked call. Contact-level STL fields only apply when `fields` is passed (one booking)."""
    fields = fields or {}
    start, booked = call["_start"], call["_booked"]
    out = {}

    # 1. triage call before the main call: an answered call of a real length between the lead-in and the meeting
    tmin = int(sop.get("triage_min_seconds") or 60)
    calls = [m for m in ms if m["kind"] in ("dial", "call_in") and m["status"] == "completed"
             and t0 - dt.timedelta(minutes=1) <= m["t"] <= start - dt.timedelta(minutes=5)]
    known = [m for m in calls if m.get("secs") is not None and m["secs"] >= tmin]
    unknown = [m for m in calls if m.get("secs") is None]
    if known:
        m = known[-1]
        b = box(YES, f"talked {max(1, round(m['secs'] / 60))} min on {fmt_et(m['t'])}", m["t"])
    elif unknown:
        m = unknown[-1]
        b = box(YES, f"answered call on {fmt_et(m['t'])}", m["t"], check="call length is not in GHL")
    elif now < start:
        b = box(NOT_DUE, "due before the call", pending=True)
    elif not msgs_ok:
        b = box(UNKNOWN, "messages could not be read")
    else:
        short = [m for m in calls if m.get("secs") is not None]
        b = box(NO, "no answered call before the meeting" + (f" ({plural(len(short), 'short call')} under "
                                                                f"{tmin} seconds)" if short else ""))
    out["triage"] = b

    # 3. pre-call video email the evening before
    rx = re.compile((sop.get("precall_subject_rx") or "required.?urgent"), re.I)
    emails = [m for m in ms if m["kind"] == "email_out" and (not m.get("subject") or rx.search(m["subject"] or ""))]
    lstart = local(start, zone)
    eve_h = hm(sop.get("evening_from"), (17, 0))
    day_before = lstart.date() - dt.timedelta(days=1)
    eve_start = to_utc(dt.datetime(day_before.year, day_before.month, day_before.day, eve_h[0], eve_h[1]), zone)
    eve_end = to_utc(dt.datetime(lstart.year, lstart.month, lstart.day), zone)
    if booked >= eve_end:
        hit = next((m for m in emails if booked <= m["t"] <= start), None)
        if hit:
            b = box(YES, f"booked after that evening; sent {fmt_et(hit['t'])}", hit["t"])
        elif now < start:
            b = box(NOT_DUE, "booked after the evening before; send it before the call", pending=True)
        else:
            b = box(NOT_DUE, f"booked {fmt_et(booked)}, after the evening before the call")
    else:
        hit = next((m for m in emails if max(eve_start, booked) <= m["t"] < eve_end), None)
        if hit:
            b = box(YES, f"email at {fmt_et(hit['t'])}", hit["t"])
        elif now < eve_end:
            b = box(NOT_DUE, f"due {fmt_day(day_before)} from {clock(dt.datetime(2000, 1, 1, *eve_h))}"
                             + ("" if zone == "eastern" else f" {ZONE_LABEL[zone]} time"), pending=True)
        elif not msgs_ok:
            b = box(UNKNOWN, "messages could not be read")
        else:
            near = next((m for m in emails if booked <= m["t"] <= start), None)
            zl = "" if zone == "eastern" else f" {ZONE_LABEL[zone]} time"
            b = box(NO, f"no pre-call email on the evening of {fmt_day(day_before)} (from "
                        f"{clock(dt.datetime(2000, 1, 1, *eve_h))}{zl})"
                        + (f"; an email went out {fmt_et(near['t'])} ET" if near else ""), near["t"] if near else None)
    if hit and not hit.get("subject") and b["a"] == YES:
        b["check"] = "email subject not shown in GHL"
    out["precall_email"] = b

    # 4. morning confirm call or text, the morning of the call before it starts
    mo = hm(sop.get("morning_from"), (5, 0))
    mu = hm(sop.get("morning_until"), (12, 0))
    after_booking = booked + dt.timedelta(minutes=30)          # the booking confirmation itself is not the confirm
    m_start = max(to_utc(dt.datetime(lstart.year, lstart.month, lstart.day, mo[0], mo[1]), zone), after_booking)
    m_until = to_utc(dt.datetime(lstart.year, lstart.month, lstart.day, mu[0], mu[1]), zone)
    touch = next((m for m in ms if m["kind"] in ("dial", "sms_out") and m_start <= m["t"] < start), None)
    if after_booking >= start or after_booking > m_until:
        b = box(NOT_DUE, f"booked {fmt_et(booked)}, the same day after the morning")
    elif touch:
        b = box(YES, f"{'call' if touch['kind'] == 'dial' else 'text'} at {fmt_et(touch['t'])}", touch["t"])
    elif now < start:
        b = box(NOT_DUE, f"due the morning of {fmt_day(lstart)}", pending=True)
    elif not msgs_ok:
        b = box(UNKNOWN, "messages could not be read")
    else:
        b = box(NO, f"no call or text the morning of {fmt_day(lstart)} before the call")
    out["morning_confirm"] = b

    # 5. showed
    st = norm(call.get("status")).replace(" ", "")
    talk_at = next((m for m in ms if m["kind"] in ("dial", "call_in") and m["status"] == "completed"
                    and (m.get("secs") or 0) >= tmin
                    and start - dt.timedelta(minutes=15) <= m["t"] <= start + dt.timedelta(minutes=90)), None)
    n = note_after(notes, start)
    if st in SHOWED_STATUS:
        b = box(YES, "marked showed in the calendar")
    elif st in NOSHOW_STATUS:
        b = box(NO, "marked no-show in the calendar")
    elif now < start:
        b = box(NOT_DUE, f"call is {fmt_et(start)}", pending=True)
    elif latest and norm(stage) in NOSHOW_STAGES:
        b = box(NO, f"deal stage is {stage}")
    elif n and NOSHOW_NOTE_RX.search(n[1]):
        b = box(NO, f"GHL note on {fmt_et(n[0])} says no-show", n[0])
    elif latest and norm(stage) in AFTER_CALL_STAGES:
        b = box(YES, f"deal moved to {stage} after the call")
    elif talk_at:
        b = box(YES, f"talked on the phone at the meeting time ({fmt_et(talk_at['t'])})", talk_at["t"])
    elif n and OUTCOME_NOTE_RX.search(n[1]):
        b = box(YES, f"post-call note on {fmt_et(n[0])}", n[0])
    else:
        b = box(UNKNOWN, "no outcome in GHL: mark it showed or no-show in the calendar")
    out["showed"] = b

    # 2. show-rate SOP followed: booking confirmation, pre-call email, morning confirm
    conf_end = booked + dt.timedelta(minutes=int(sop.get("confirm_minutes_after_booking") or 60))
    conf = next((m for m in ms if m["kind"] in ("sms_out", "email_out") and booked - dt.timedelta(minutes=1) <= m["t"]
                 <= conf_end), None)
    if conf:
        cpart = (YES, f"booking confirmed by {'text' if conf['kind'] == 'sms_out' else 'email'} {fmt_et(conf['t'])}")
    elif now < conf_end:
        cpart = (NOT_DUE, "booking confirmation due")
    else:
        cpart = (NO, f"no text or email within {int(sop.get('confirm_minutes_after_booking') or 60)} min of booking")
    parts = [cpart, (out["precall_email"]["a"], "pre-call email: " + out["precall_email"]["a"].lower()),
             (out["morning_confirm"]["a"], "morning confirm: " + out["morning_confirm"]["a"].lower())]
    why = "; ".join(p[1] for p in parts)
    if out["precall_email"]["pending"] or out["morning_confirm"]["pending"] or cpart[0] == NOT_DUE and now < conf_end:
        b = box(NOT_DUE, why, pending=True)
    elif any(p[0] == NO for p in parts):
        b = box(NO, why)
    elif any(p[0] == UNKNOWN for p in parts):
        b = box(UNKNOWN, why)
    else:
        b = box(YES, why)
    out["show_sop"] = b

    for key, role in CALL_FIELD.items():
        if role in fields and not (key == "showed" and not latest):
            out[key] = apply_field(out[key], fields[role], FIELD_LABEL[key])
    return out


def qualified(lead, stage, settings):
    q = settings.get("qualified") or {}
    code = code_str((lead.get("fields") or {}).get("reply_code"))
    ov = norm((q.get("overrides") or {}).get(code)) if code else ""
    if ov in ("yes", "qualified", "true"):
        return True, "marked qualified in settings"
    if ov in ("no", "not qualified", "unqualified", "false"):
        return False, "marked not qualified in settings"
    if norm(stage) in {norm(s) for s in q.get("unqualified_stages") or []}:
        return False, f"deal stage {stage}"
    rx = re.compile(q.get("unqualified_reason_rx") or r"disqual|unqualif|not qualified", re.I)
    for role, label in (("outcome_reason", "STL Outcome Reason"), ("outcome", "STL Outcome")):
        v = flat((lead.get("fields") or {}).get(role))
        if v and rx.search(v):
            return False, f"{label}: {scrub(v)[:40]}"
    return True, "not marked unqualified in GHL"


# ---------------------------------------------------------------- the whole evidence

def answers(boxes, order):
    return "".join(CHAR[boxes[k]["a"]] for k, _ in order)


def read_prev_state(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        m = re.search(r'<script type="application/json" id="ls-state">(.*?)</script>', f.read(), re.S)
    if not m:
        return None
    try:
        st = json.loads(m.group(1).replace("<\\/", "</"))
    except ValueError:
        return None
    return st if isinstance(st, dict) and st.get("v") == 1 else None


def rate(rows, keys):
    y = sum(1 for r in rows for k in keys if r["boxes"][k]["a"] == YES)
    n = sum(1 for r in rows for k in keys if r["boxes"][k]["a"] == NO)
    return {"yes": y, "no": n, "pct": round(100.0 * y / (y + n)) if (y + n) else None}


def build(raw, settings, now=None, prev=None, entered_through=None):
    now = now or et.now_utc()
    today = et.to_et(now).date()
    sop = settings.get("sop") or {}
    loc = raw.get("location_id") or ""
    live = live_start_utc(settings)
    win = clock_window(settings, today)
    win_end = et.parse(win["end_utc"])
    stages = raw.get("stages") or {}
    joey = raw.get("joey_contact")
    excluded = {"test": 0, "before_live": 0, "duplicate": 0, "not_read": 0}

    # leads
    lead_rows, by_cid, seen_keys = [], {}, {}
    cand = []
    for cid, lead in (raw.get("leads") or {}).items():
        if is_excluded(lead, joey):
            excluded["test"] += 1
            continue
        t0, src = lead_in(lead, live)
        if not t0 or (t0 < live and not raw.get("probe")):
            excluded["before_live"] += 1
            continue
        cand.append((t0, cid, src))
    cand.sort()
    for t0, cid, src in cand:
        lead = raw["leads"][cid]
        block = (raw.get("messages") or {}).get(cid)
        if block is None:
            excluded["not_read"] += 1
            continue
        fields = lead.get("fields") or {}
        zone = zone_of(fields.get("tz") or lead.get("timezone"))
        ms = norm_msgs(block, raw.get("call_details"), sop)
        msgs_ok = bool(block.get("ok", True))
        oldest = et.parse(block.get("oldest"))
        early_missing = bool(block.get("truncated")) and oldest is not None and oldest > t0 + dt.timedelta(minutes=10)
        opps = sorted(lead.get("opps") or [], key=lambda o: str(o.get("updatedAt") or o.get("createdAt") or ""))
        stage = stages.get(opps[-1].get("stageId"), "") if opps else ""
        dup_of = next((seen_keys[k] for k in lead.get("dup") or [] if k in seen_keys), None)
        for k in lead.get("dup") or []:
            seen_keys.setdefault(k, cid)
        boxes, facts = lead_boxes(t0, zone, ms, sop, now, fields, msgs_ok, early_missing)
        q, qwhy = qualified(lead, stage, settings)
        code = code_str(fields.get("reply_code"))
        row = {
            "cid": cid, "hash": short_hash(loc, cid), "first": scrub(lead.get("first") or ""), "code": code,
            "t0": t0.isoformat(), "t0_et": fmt_et(t0), "t0_date": et.to_et(t0).date().isoformat(), "t0_src": src,
            "zone": ZONE_LABEL.get(zone, "Eastern"), "after_hours": facts["after_hours"], "stage": stage,
            "qualified": q, "qualified_why": qwhy, "duplicate": bool(dup_of),
            "boxes": boxes, "answers": answers(boxes, LEAD_BOXES),
            "ready": not any(boxes[k]["pending"] for k, _ in LEAD_BOXES),
            "field_count": sum(1 for r in prof.STL_BOX_ROLES if r in fields),
            "checks": [f"{dict(LEAD_BOXES)[k]}: {boxes[k]['check']}" for k, _ in LEAD_BOXES if boxes[k].get("check")],
        }
        due = [k for k in SOP_LEAD if boxes[k]["a"] in (YES, NO)]
        row["sop_yes"], row["sop_due"] = sum(1 for k in due if boxes[k]["a"] == YES), len(due)
        if dup_of:
            excluded["duplicate"] += 1
            row["dup_of"] = short_hash(loc, dup_of)
        lead_rows.append(row)
        by_cid[cid] = (row, lead, zone, ms, msgs_ok, stage)

    # calls
    s_calls = settings.get("calls") or {}
    merged = merge_calls(raw.get("events") or [], by_cid, s_calls)
    per_lead = {}
    for e in merged:
        if e["_state"] == "booked":
            per_lead.setdefault(e["contactId"], []).append(e)
    call_rows = []
    for e in merged:
        row_l, lead, zone, ms, msgs_ok, stage = by_cid[e["contactId"]]
        booked_list = per_lead.get(e["contactId"], [])
        past = [x for x in booked_list if x["_start"] <= now]
        latest = bool(past) and past[-1] is e
        single = len(booked_list) == 1 and booked_list[0] is e
        t0 = et.parse(row_l["t0"])
        boxes = call_boxes(e, t0, zone, ms, sop, now, (raw.get("notes") or {}).get(e["contactId"]),
                           (lead.get("fields") or {}) if single else None, stage, latest, msgs_ok)
        rule = s_calls.get("count_rule") or "booked_at"
        when = e["_booked"] if rule == "booked_at" else e["_start"]
        in_window = live <= when < win_end
        counts = e["_state"] == "booked" and in_window and row_l["qualified"] and not row_l["duplicate"]
        if e["_state"] != "booked":
            why = {"moved": "moved to a new time (the new booking counts)", "cancelled": "cancelled"}[e["_state"]]
        elif not in_window:
            why = "booked outside the 90-day window" if rule == "booked_at" else "outside the 90-day window"
        elif row_l["duplicate"]:
            why = "duplicate lead"
        elif not row_l["qualified"]:
            why = "not qualified: " + row_l["qualified_why"]
        else:
            why = "counts"
        n = note_after((raw.get("notes") or {}).get(e["contactId"]), e["_start"])
        brief = flat((lead.get("fields") or {}).get("meeting_brief"))
        if n:
            notes = {"src": f"GHL note, {fmt_et(n[0])}", "text": sentences(n[1])}
        elif brief:
            notes = {"src": "meeting brief, written before the call", "text": sentences(brief)}
        else:
            notes = {"src": "", "text": ""}
        ready_at = e["_start"] + dt.timedelta(hours=float(s_calls.get("ready_hours_after_start") or 3))
        row = {
            "hash": short_hash(loc, e.get("id")), "lead_hash": row_l["hash"], "first": row_l["first"],
            "code": row_l["code"], "start": e["_start"].isoformat(), "start_et": fmt_et(e["_start"]),
            "start_date": et.to_et(e["_start"]).date().isoformat(), "booked_et": fmt_et(e["_booked"]),
            "booked_at": e["_booked"].isoformat(), "calendar": "Discovery Call" if e["cal"] == "discovery" else "Lead Suite",
            "state": e["_state"], "upcoming": e["_start"] > now, "in_window": in_window, "counts": counts,
            "count_why": why, "qualified": row_l["qualified"], "boxes": boxes, "answers": answers(boxes, CALL_BOXES),
            "ready": e["_state"] == "booked" and now >= ready_at and not any(boxes[k]["pending"] for k, _ in CALL_BOXES),
            "notes": notes,
            "checks": [f"{dict(CALL_BOXES)[k]}: {boxes[k]['check']}" for k, _ in CALL_BOXES if boxes[k].get("check")],
        }
        due = [k for k in SOP_CALL if boxes[k]["a"] in (YES, NO)]
        row["sop_yes"], row["sop_due"] = sum(1 for k in due if boxes[k]["a"] == YES), len(due)
        call_rows.append(row)

    ev_leads = [r for r in lead_rows if not r["duplicate"]]
    ev_calls = [r for r in call_rows if r["state"] == "booked"]
    sop_rates = {"leads": rate(ev_leads, SOP_LEAD), "calls": rate(ev_calls, SOP_CALL),
                 "all": rate(ev_leads, SOP_LEAD)}
    a = sop_rates["all"]
    c = sop_rates["calls"]
    y, n = a["yes"] + c["yes"], a["no"] + c["no"]
    sop_rates["all"] = {"yes": y, "no": n, "pct": round(100.0 * y / (y + n)) if (y + n) else None}

    board = scoreboard(settings, win, call_rows, ev_leads, sop_rates, today)
    portal, state = portal_rows(ev_leads, ev_calls, prev, entered_through, settings, loc, now)
    field_report = {
        "found": sorted(k for k in raw.get("field_ids") or {} if k in prof.STL_BOX_ROLES or k == "lead_in_at"),
        "missing": sorted(r for r in prof.STL_BOX_ROLES + ("lead_in_at",) if r not in (raw.get("field_ids") or {})),
        "how": raw.get("field_how") or {},
        "leads_with_any": sum(1 for r in ev_leads if r["field_count"]),
        "leads": len(ev_leads),
    }
    return {
        "generated_at": now.isoformat(), "generated_et": fmt_et(now), "location_key": raw.get("location_key"),
        "location_hash": short_hash(loc, "loc"), "probe": bool(raw.get("probe")), "fatal": raw.get("fatal"),
        "window": win, "scoreboard": board, "sop": sop_rates, "leads": lead_rows, "calls": call_rows,
        "portal": portal, "state": state, "excluded": excluded, "field_report": field_report,
        "conditions": conditions(settings, board, sop_rates, ev_leads),
        "errors": raw.get("errors") or [], "bounds": raw.get("bounds") or {},
        "settings_used": {"sop": {k: v for k, v in sop.items() if not k.startswith("_")},
                          "count_rule": s_calls.get("count_rule") or "booked_at",
                          "target": int((settings.get("contract") or {}).get("target_qualified_calls") or 30)},
    }


def scoreboard(settings, win, calls, leads, sop_rates, today):
    target = int((settings.get("contract") or {}).get("target_qualified_calls") or 30)
    counted = [c for c in calls if c["counts"]]
    n = len(counted)
    booked_in_window = [c for c in calls if c["state"] == "booked" and c["in_window"]]
    held = sum(1 for c in counted if c["boxes"]["showed"]["a"] == YES)
    unq = sum(1 for c in booked_in_window if not c["qualified"])
    cancelled = sum(1 for c in calls if c["state"] == "cancelled" and c["in_window"])
    upcoming = sum(1 for c in counted if c["upcoming"])
    used, left = win["used"], win["left"]
    pace = round(n * win["days"] / used) if used else 0
    need = max(0, target - n)
    end = dt.date.fromisoformat(win["end"])
    lp = sop_rates["leads"]["pct"]
    proof_no = sum(1 for r in leads for k in SOP_LEAD if r["boxes"][k]["a"] == NO)
    proof_unknown = sum(1 for r in leads for k in SOP_LEAD if r["boxes"][k]["a"] == UNKNOWN)
    if not win["started"]:
        line = f"Ads are not live yet. The window starts {fmt_day(dt.date.fromisoformat(win['live']))}."
    elif n >= target:
        line = (f"{n} qualified calls are booked, so Lead Suite has hit the {target}-call number. The refund does not "
                f"apply unless some of these calls were not qualified.")
    elif not win["over"]:
        line = (f"{n} of {target} qualified calls with {plural(left, 'day')} left. At this pace the window ends with "
                f"about {plural(pace, 'call')}. If it ends under {target}, the refund rests on the proof: every lead's checklist "
                f"({'no boxes yet' if lp is None else str(lp) + '% of due boxes done'}), the portal rows, and ad spend "
                f"from Meta and Mercury.")
    else:
        line = (f"The window closed {fmt_day(end)} with {n} of {target} qualified calls. That is under the number, so "
                f"the refund applies if the proof holds. Gather it now: this page, the portal, Meta and Mercury.")
    return {"target": target, "qualified_booked": n, "booked_in_window": len(booked_in_window), "held": held,
            "upcoming": upcoming, "unqualified": unq, "cancelled": cancelled, "need": need, "pace": pace,
            "leads": len(leads), "leads_booked": len({c["lead_hash"] for c in counted}), "line": line,
            "proof_no": proof_no, "proof_unknown": proof_unknown, "today": today.isoformat()}


def conditions(settings, board, sop_rates, leads):
    out = []
    for c in settings.get("conditions") or []:
        row = {"key": c.get("key"), "text": c.get("text"), "proof": c.get("proof"), "where": c.get("where")}
        if c.get("key") == "every_lead":
            lp = sop_rates["leads"]["pct"]
            row["live"] = (f"{plural(len(leads), 'lead')} since ads went live; "
                           + ("no boxes due yet" if lp is None else f"{lp}% of due boxes done")
                           + (f"; {plural(board['proof_no'], 'box', 'boxes')} marked No" if board["proof_no"] else "")
                           + (f"; {board['proof_unknown']} unknown" if board["proof_unknown"] else "") + ".")
        out.append(row)
    return out


def portal_rows(leads, calls, prev, entered_through, settings, loc, now):
    """Which finished rows still need typing into the portal. Each row is listed once: after a page lists it, the next
    run treats it as typed in, unless its answers changed (then it comes back as changed). A date in settings counts
    every row on or before it as typed in. A date Joey gives on demand (`entered_through`) also brings back every
    finished row after it, even ones an earlier page listed, for the week he skipped."""
    loc_h = short_hash(loc, "loc")
    prev_ok = bool(prev) and prev.get("loc") == loc_h
    prev_rows = dict(prev.get("rows") or {}) if prev_ok else {}
    explicit = bool(entered_through)
    thru = entered_through or (settings.get("portal") or {}).get("entered_through")
    if not explicit and prev_ok and prev.get("entered_through") and (not thru or prev["entered_through"] > thru):
        thru = prev["entered_through"]
    thru_d = dt.date.fromisoformat(thru) if thru else None
    out = {"new_leads": [], "changed_leads": [], "new_calls": [], "changed_calls": [], "waiting_leads": [],
           "waiting_calls": [], "first_run": not prev_ok and not thru_d, "entered_through": thru,
           "relisted": explicit, "prev_date": prev.get("date") if prev_ok else None}
    rows = dict(prev_rows)
    for kind, items, date_key in (("leads", leads, "t0_date"), ("calls", calls, "start_date")):
        for r in items:
            key = ("L" if kind == "leads" else "C") + r["hash"]
            if not r["ready"]:
                out["waiting_" + kind].append(r["hash"])
                continue
            on_or_before = bool(thru_d) and dt.date.fromisoformat(r[date_key]) <= thru_d
            if key in prev_rows and prev_rows[key] != r["answers"] and (on_or_before or not explicit):
                out["changed_" + kind].append({"hash": r["hash"], "was": prev_rows[key]})
            elif on_or_before or (key in prev_rows and not explicit):
                pass                                   # already in the portal
            else:
                out["new_" + kind].append(r["hash"])
            rows[key] = r["answers"]
    state = {"v": 1, "loc": loc_h, "date": et.to_et(now).date().isoformat(), "entered_through": thru, "rows": rows}
    return out, state


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score the Lead Suite evidence.")
    ap.add_argument("--raw", default=os.path.join(OUT_DIR, "raw.json"))
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "evidence.json"))
    ap.add_argument("--settings", default=prof.SETTINGS)
    ap.add_argument("--prev", help="the page as last published (from the Artifact read)")
    ap.add_argument("--entered-through", help="Eastern date: rows on or before it are already in the portal")
    ap.add_argument("--now", help="ISO time (tests)")
    a = ap.parse_args(argv)
    with open(a.raw, encoding="utf-8") as f:
        raw = json.load(f)
    ev = build(raw, prof.load_settings(a.settings), now=et.parse(a.now) if a.now else None,
               prev=read_prev_state(a.prev), entered_through=a.entered_through)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print(ev["scoreboard"]["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
