"""Call prep: find the day's sales calls, build the prep data, render the Call Prep page in Joey's fixed format.

Files live in /tmp/call_engine (or $CALL_ENGINE_DIR). Commands (run from the repo root):

  match   --google G.json [--ghl] [--day YYYY-MM-DD] [--existing E] [--out calls.json]
          G.json holds the Google Calendar events the model listed: {"primary": <list_events result or a list of
          events>, "surven": ..., "work": ...} (work = the busy-only surven.ai calendar). --ghl also reads the Surven HQ GoHighLevel calendars
          (Discovery Call, Client Calls, Lead Suite, Joseph) read-only; it needs the Surven HQ environment.
          E is the Call Prep page as fetched (its <page url=...>Title</page> lines) or a JSON list of titles.
          Prints {"calls": [...to prep...], "not_prepped": [...], "hidden": [...], "notes": [...]}.
  gather  --calls calls.json [--meetings fathom_list.txt] [--ghl] [--out prep.json]
          Adds GHL context (contact, deal stage, last messages, notes), prior Fathom meetings, the offer the
          rules prescribe, reminders and objections to expect. The model then fills each call's "page" and facts.
  render  --prep prep.json [--out-dir DIR]
          Re-runs the offer rules on the final facts, validates the page, copy-checks Joey-facing text, writes one
          <key>.md per call plus pages.json. Exit 1 if a page breaks the format (the issues say what to fix).
  finish  [--pages pages.json] [--created created.json] [--dry-run]
          Writes the final one-line message and, when pages were written, sms.txt for shared.notify.

The page format is LOCKED by Joey (8/12): Meet link at the top, then QUALIFYING, SUSPECT PAINS, TIMELINE, WANTS,
OTHER NOTES, then a red do-different callout. One small screen, one-line bullets, shorter beats longer.
"""
import argparse
import datetime as _dt
import json
import os
import re
import sys

from shared import et
from tools.call_engine import rules
from tools.call_engine import meetings as mt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.environ.get("CALL_ENGINE_DIR", "/tmp/call_engine")


def load_config():
    with open(os.path.join(ROOT, "config", "surven.json"), encoding="utf-8") as f:
        return json.load(f)


def load_offer_rules():
    with open(os.path.join(HERE, "offer_rules.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- events

URL_RX = re.compile(r"https?://(?:meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}|[\w.-]*zoom\.us/j/\d+[^\s\"<>]*|"
                    r"teams\.microsoft\.com/[^\s\"<>]+)", re.I)
CLIENT_CALL_TITLE = re.compile(r"(^|[^a-z0-9])(on[\s-]*boarding|onboard(ed)?|go[\s-]*live|kick[\s-]?off)([^a-z0-9]|$)", re.I)
COACH_RX = re.compile(r"\bmaster\s?mind\b|\bcoach(?:ing)?\b|\boffer\s+operators\b|\baccount\s+manager\b|"
                      r"\bgroup\s+call\b|\bstudents\b", re.I)
WEAK_COACH_RX = re.compile(r"\(ls\)|\blead\s?suite\b|\bclient\s+call\b", re.I)
CARE_WORDS = re.compile(r"\bassisted\s+living\b|\bcare\s+homes?\b|\bmemory\s+care\b|\bbeds?\b|\bresidential\s+care\b|"
                        r"\bboard\s+and\s+care\b|\bsenior\s+living\b|\bdiscovery\b|\bresidents?\b|\bgroup\s+home\b|"
                        r"\badult\s+family\s+home\b|\bpersonal\s+care\s+home\b", re.I)
NAME_RX = [
    re.compile(r"(?:joey|joseph)(?:\s+(?!x\b|and\b)[a-z]+\.?)?\s*(?:x|<>|&|/|\+|and)\s*(?P<n>[^|:()]+?)\s*$", re.I),
    re.compile(r"^(?P<n>[^|:()]+?)\s*(?:x|<>|&|/|and)\s*(?:joey|joseph)\b", re.I),
    re.compile(r"\bsurven\s*(?:&|x|and|<>)\s*(?P<n>[^|:()]+?)\s*$", re.I),
    re.compile(r"\bdiscovery\s+call\s*[,:|]\s*(?P<n>[^|:()]+?)\s*$", re.I),
    re.compile(r"\b(?:call|meeting|chat)\s+with\s+(?!surven\b|joey\b|joseph\b)(?P<n>[^|:()&]+?)\s*$", re.I),
    re.compile(r"^(?P<n>[A-Z][\w'.]+(?:\s+[A-Z][\w'.]+)?)\s+(?:discovery|disco|call|follow[\s-]?up|onboarding|close)\b"),
]
NAME_STOP = re.compile(r"\b(?:discovery|call|follow[\s-]?up|onboarding|closing|close|meeting|zoom|google\s+meet)\b", re.I)


def self_identity(cfg, extra=None):
    emails = {e.lower() for e in (extra or []) if e}
    g = (cfg.get("google") or {}).get("joey_gmail")
    if g:
        emails.add(g.lower())
    domains = {"surven.ai"} | {d.lower() for d in cfg.get("cold_email_domains") or []}
    return emails, domains


def _is_self(att, emails, domains):
    if att.get("self"):
        return True
    e = (att.get("email") or "").lower()
    return bool(e) and (e in emails or e.split("@")[-1] in domains)


def _meet_link(ev):
    for v in (ev.get("conferenceUrl"), ev.get("hangoutLink"),
              ((ev.get("conferenceData") or {}).get("videoEntryPoint") or {}).get("uri")):
        if v:
            return v
    for ep in (ev.get("conferenceData") or {}).get("entryPoints") or []:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    for field in ("location", "address", "description"):
        m = URL_RX.search(ev.get(field) or "")
        if m:
            return m.group(0)
    return None


def _events_of(v):
    if isinstance(v, dict):
        return v.get("events") or v.get("items") or []
    return v or []


def norm_google(ev, cal, emails, domains):
    st = (ev.get("start") or {})
    start = st.get("dateTime") if isinstance(st, dict) else ev.get("start")
    if not start:
        return None                      # all-day items are never calls
    en = (ev.get("end") or {})
    atts = [{"email": a.get("email"), "name": a.get("displayName"), "self": a.get("self"),
             "response": a.get("responseStatus")} for a in ev.get("attendees") or []]
    declined = any(a.get("self") and a.get("response") == "declined" for a in atts)
    ext = [a for a in atts if not _is_self(a, emails, domains)]
    return {"source": "google", "calendar": cal, "id": ev.get("id"), "title": (ev.get("summary") or "").strip(),
            "start": et.parse(start), "end": et.parse(en.get("dateTime") if isinstance(en, dict) else en),
            "description": (ev.get("description") or "")[:1500], "external": ext, "attendees": atts,
            "meet_link": _meet_link(ev), "status": "cancelled" if (ev.get("status") == "cancelled" or declined) else "ok",
            "hidden": not ev.get("summary") and not atts, "contact_id": None, "calendar_kind": None}


# HQ GoHighLevel calendar key (config/surven.json ghl.hq.calendars) -> the kind of call booked there.
GHL_CAL_KIND = {"discovery_call": "discovery", "lead_suite_personal": "discovery", "client_calls": "onboarding"}


def norm_ghl(ev, cal_key):
    if ev.get("deleted"):
        return None
    st = str(ev.get("appointmentStatus") or ev.get("status") or "").lower()
    return {"source": "ghl", "calendar": cal_key, "id": ev.get("id"), "title": (ev.get("title") or "").strip(),
            "start": et.parse(ev.get("startTime")), "end": et.parse(ev.get("endTime")), "description": "",
            "external": [], "attendees": [], "meet_link": _meet_link(ev),
            "status": "cancelled" if st in ("cancelled", "invalid", "noshow", "no_show") else "ok",
            "hidden": False, "contact_id": ev.get("contactId"),
            "calendar_kind": GHL_CAL_KIND.get(cal_key)}


def guess_name(title, external=None):
    t = re.sub(r"^\s*\([^)]*\)\s*", "", (title or "").strip())
    for rx in NAME_RX:
        m = rx.search(t)
        if m:
            n = NAME_STOP.sub("", m.group("n")).strip(" -|,.")
            n = re.sub(r"\s{2,}", " ", n)
            if n and len(n) <= 40 and not re.search(r"\b(?:joey|joseph)\b", n, re.I):
                return n
    for a in external or []:
        if a.get("name"):
            return a["name"]
        if a.get("email"):
            return a["email"].split("@")[0].replace(".", " ").title()
    return None


def classify_event(e):
    """-> (kind, reason). Kinds that get a prep page: discovery, close, follow-up, onboarding."""
    if e["status"] == "cancelled":
        return "skip", "cancelled or declined"
    if e["hidden"]:
        return "hidden", "busy block with no title (calendar shares free/busy only)"
    title, desc = e["title"], e["description"]
    if e["source"] == "ghl":
        if CLIENT_CALL_TITLE.search(title):
            return "onboarding", "client call title"
        for kind, rx in mt.TITLE_RULES:
            if kind in ("close", "follow-up", "discovery") and rx.search(title):
                return kind, "GHL appointment title"
        if e["calendar_kind"]:
            return e["calendar_kind"], "GHL %s calendar" % e["calendar"]
        if COACH_RX.search(title):
            return "coaching", "coaching title"
        return "discovery", "GHL appointment with a contact"
    if COACH_RX.search(title) or any(
            (a.get("email") or "").lower().endswith(tuple("@" + d for d in mt.COACH_DOMAINS)) for a in e["external"]):
        return "coaching", "coaching or group call"
    for kind, rx in mt.TITLE_RULES:
        if kind != "coaching" and rx.search(title):
            return kind, "title"
    if COACH_RX.search(desc) or WEAK_COACH_RX.search(title) or (
            WEAK_COACH_RX.search(desc) and re.search(r"\baccount\s+manager\b|\b1-1\b", desc, re.I)):
        return "coaching", "coaching call (description)"
    if e["external"] and (CARE_WORDS.search(title) or CARE_WORDS.search(desc)):
        return "discovery", "outside attendee and care words"
    if e["external"]:
        return "external_unknown", "outside attendee, nothing says sales"
    return "internal", "time block"


PREP_KINDS = ("discovery", "close", "follow-up", "onboarding")


def _tok(s):
    return {t for t in re.findall(r"[a-z]{3,}", (s or "").lower())} - {"joey", "joseph", "call", "discovery", "surven"}


def dedupe(items):
    """Same call on GHL and Google: start within 10 minutes and a shared name token or attendee email."""
    out = []
    for e in sorted(items, key=lambda x: (0 if x["source"] == "ghl" else 1, x["start"] or et.now_utc())):
        twin = None
        for o in out:
            if not (e["start"] and o["start"]) or abs((e["start"] - o["start"]).total_seconds()) > 600:
                continue
            emails = {(a.get("email") or "").lower() for a in e["external"]} & {(a.get("email") or "").lower() for a in o["external"]}
            if (_tok(e.get("name")) & _tok(o.get("name"))) or (emails - {""}):
                twin = o
                break
        if twin:
            twin["sources"].append("%s:%s" % (e["source"], e["calendar"]))
            twin["meet_link"] = twin["meet_link"] or e["meet_link"]
            twin["external"] = twin["external"] or e["external"]
            twin["contact_id"] = twin["contact_id"] or e["contact_id"]
        else:
            e["sources"] = ["%s:%s" % (e["source"], e["calendar"])]
            out.append(e)
    return out


def parse_existing(text):
    """Call Prep page fetch (or a JSON list) -> list of {"title", "url"}."""
    text = (text or "").strip()
    if not text:
        return []
    if text.startswith("["):
        return [x if isinstance(x, dict) else {"title": x, "url": None} for x in json.loads(text)]
    if text.startswith("{"):
        d = json.loads(text)
        text = d.get("text") or json.dumps(d)
    out = []
    for m in re.finditer(r"<page\s+url=\\?\"(?P<url>[^\"\\]+)\\?\"[^>]*>\s*(?P<title>.*?)\s*</page>", text, re.S):
        out.append({"title": re.sub(r"\s+", " ", m.group("title")).strip(), "url": m.group("url")})
    return out


def day_token(d):
    return "%d/%d" % (d.month, d.day)


def already_prepped(first, d, existing):
    if not first:
        return None
    tok = day_token(d)
    for p in existing:
        t = (p.get("title") or "").lower()
        if first.lower() in t and re.search(r"(?<![\d/])%s(?![\d])" % re.escape(tok), t):
            return p
    return None


def ghl_events(day, cfg):
    """Read the HQ GoHighLevel calendars for one ET day. Returns (events, note)."""
    from shared import ghl
    hq = cfg["ghl"]["hq"]
    if not ghl.check_access(hq["location"]):
        return [], "Surven HQ GoHighLevel is not readable from this environment"
    lo = et.et_to_utc(_dt.datetime.combine(day, _dt.time(0, 0)))
    hi = et.et_to_utc(_dt.datetime.combine(day + _dt.timedelta(days=1), _dt.time(0, 0)))
    out = []
    for key, cal_id in (hq.get("calendars") or {}).items():
        r = ghl.calendar_events(hq["location"], cal_id, lo.timestamp() * 1000, hi.timestamp() * 1000)
        if isinstance(r, dict):
            return out, "GHL calendar read failed (%s)" % r.get("error")
        for ev in r:
            if ev.get("calendarId") and ev["calendarId"] != cal_id:
                continue
            ev["_calendar_key"] = key
            out.append(ev)
    return out, None


def match(google, day, cfg, ghl_raw=None, existing=None, self_emails=None):
    emails, domains = self_identity(cfg, self_emails)
    items = []
    for cal, v in (google or {}).items():
        for ev in _events_of(v):
            n = norm_google(ev, cal, emails, domains)
            if n:
                items.append(n)
    for ev in ghl_raw or []:
        n = norm_ghl(ev, ev.get("_calendar_key") or ev.get("calendarId"))
        if n:
            items.append(n)
    day_items = [e for e in items if e["start"] and et.to_et(e["start"]).date() == day]
    for e in day_items:
        e["kind"], e["why"] = classify_event(e)
        e["name"] = guess_name(e["title"], e["external"])
    calls = dedupe([e for e in day_items if e["kind"] in PREP_KINDS])
    out = {"day": day.isoformat(), "calls": [], "not_prepped": [], "hidden": [], "notes": [],
           "existing": [{"title": p.get("title"), "url": p.get("url")} for p in existing or []]}
    for e in sorted(calls, key=lambda x: x["start"]):
        s_et = et.to_et(e["start"])
        first = (e["name"] or "").split()[0] if e["name"] else None
        ex = already_prepped(first, day, existing or [])
        ext_email = next((a.get("email") for a in e["external"] if a.get("email")), None)
        key = "%s-%s" % (e["source"], re.sub(r"[^A-Za-z0-9]", "", str(e["id"]))[:24])
        out["calls"].append({
            "key": key, "kind": e["kind"], "why": e["why"], "title": e["title"], "start_utc": e["start"].isoformat(),
            "start_et": s_et.strftime("%Y-%m-%d %H:%M"), "time_et": s_et.strftime("%I:%M %p").lstrip("0"),
            "day_token": day_token(day), "name": e["name"], "first": first, "email": ext_email,
            "ghl_contact_id": e["contact_id"], "meet_link": e["meet_link"], "sources": e["sources"],
            "already_prepped": bool(ex), "existing_url": ex.get("url") if ex else None,
            "page_title": "%s Call Prep %s" % (e["name"] or "Unknown", day_token(day))})
    visible = [e for e in day_items if e["kind"] != "hidden" and e["status"] != "cancelled"]
    for e in day_items:
        if e["kind"] == "hidden" and any(abs((e["start"] - v["start"]).total_seconds()) <= 300 for v in visible):
            continue        # the same event, readable on another calendar
        if e["kind"] == "hidden":
            out["hidden"].append({"calendar": e["calendar"], "time_et": et.to_et(e["start"]).strftime("%I:%M %p").lstrip("0")})
        elif e["kind"] in ("external_unknown",):
            out["not_prepped"].append({"title": e["title"], "time_et": et.to_et(e["start"]).strftime("%I:%M %p").lstrip("0"),
                                       "kind": e["kind"], "why": e["why"]})
    return out


# ---------------------------------------------------------------- gather

KEEP_FIELDS = ("Total Beds", "Community Type", "Outreach Outcome", "Referral Info", "Preferred Method", "Outreach Status")


def ghl_context(cid=None, email=None, cfg=None):
    """Read-only GHL HQ context for one prospect. Returns a dict; never raises on API errors."""
    from shared import ghl
    cfg = cfg or load_config()
    hq = cfg["ghl"]["hq"]
    loc = hq["location"]
    if not cid and email:
        found = ghl.search_contacts(loc, filters=[{"field": "email", "operator": "eq", "value": email}], page_limit=5,
                                    max_pages=1)
        if isinstance(found, list) and found:
            cid = found[0].get("id")
    if not cid:
        return {"status": "not found"}
    c = ghl.contact(cid)
    if not ghl.ok(c) or not isinstance(c, dict) or c.get("error"):
        return {"status": "read failed", "contact_id": cid}
    fmap = ghl.field_map(loc)
    fields = {}
    for f in c.get("customFields") or c.get("customField") or []:
        name = fmap.get(f.get("id"), "")
        if name in KEEP_FIELDS:
            fields[name] = f.get("value", f.get("field_value"))
        if f.get("id") == hq.get("code_field_email_reply"):
            fields["Email Reply Code"] = f.get("value", f.get("field_value"))
    out = {"status": "ok", "contact_id": cid,
           "contact": {k: c.get(k) for k in ("firstName", "lastName", "companyName", "email", "city", "state", "website",
                                              "source", "dateAdded")},
           "tags": c.get("tags") or [], "fields": fields, "deals": [], "messages": [], "notes": []}
    pipes = ghl.pipelines(loc)
    names = {}
    if isinstance(pipes, list):
        for p in pipes:
            for s in p.get("stages") or []:
                names[s.get("id")] = (p.get("name"), s.get("name"))
    r = ghl.call("/opportunities/search", {"location_id": loc, "contact_id": cid, "limit": 20, "status": "all"})
    opps = (r.get("opportunities") or []) if ghl.ok(r) else None
    if isinstance(opps, list):
        for o in opps:
            if (o.get("contactId") or (o.get("contact") or {}).get("id")) == cid:
                pn, sn = names.get(o.get("pipelineStageId"), (None, None))
                out["deals"].append({"pipeline": pn, "stage": sn, "status": o.get("status"),
                                     "updated": o.get("updatedAt") or o.get("lastStageChangeAt")})
    convs = ghl.conversations(loc, contact_id=cid, limit=5)
    if isinstance(convs, list) and convs:
        msgs = ghl.messages(convs[0].get("id"), max_pages=1)
        if isinstance(msgs, list):
            msgs = sorted(msgs, key=lambda m: m.get("dateAdded") or "")[-8:]
            for m in msgs:
                out["messages"].append({"date": (m.get("dateAdded") or "")[:16], "direction": m.get("direction"),
                                        "type": m.get("messageType") or m.get("type"),
                                        "body": " ".join((m.get("body") or "").split())[:400]})
    nts = ghl.notes(cid)
    if isinstance(nts, list):
        out["notes"] = [" ".join((n.get("body") or "").split())[:300] for n in nts[:3]]
    return out


def derive_signals(texts):
    blob = " \n ".join(t for t in texts if t)
    return sorted(k for k, rx in rules.SIGNAL_WORDS.items() if re.search(rx, blob, re.I))


def _int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def prescribe(facts, offer=None):
    """facts -> {"tier", "label", "guarantee", "why", "on_call", "verify"} per offer_rules.json."""
    offer = offer or load_offer_rules()
    tiers = offer["tiers"]
    ctype = (facts.get("community_type") or "").lower()
    empty = _int(facts.get("empty_beds"))
    reason, tier = None, None
    if ctype and any(w in ctype for w in offer["scope"]["out"]):
        tier, reason = "route_out", "Out of scope: %s." % facts.get("community_type")
    elif facts.get("operating") is False:
        tier, reason = "route_out", "Not operating yet. Keep warm."
    elif facts.get("below_break_even") is True:
        tier, reason = "route_out", "Below break-even. No financing."
    elif facts.get("travel_nurse") is True:
        tier = "travel_nurse"
    elif facts.get("can_fund_ads") is False:
        tier = "referral_starter"
    elif empty is not None and empty >= offer["resident_headline_min_empty_beds"] and facts.get("staffing_ok") is True:
        tier = "full_bed_system_resident_headline"
    else:
        tier = "full_bed_system"
    t = tiers[tier]
    why = [t["why_template"].format(reason=reason or "")] if t.get("why_template") else []
    if tier == "full_bed_system" and empty is not None and empty >= offer["resident_headline_min_empty_beds"]:
        why.append("%d empty, but staffing is not confirmed: no resident promise until the capacity screen." % empty)
    elif tier == "full_bed_system" and empty is not None:
        why.append("%d empty bed%s." % (empty, "" if empty == 1 else "s"))
    if facts.get("uses_placement_agents"):
        why.append("Uses placement agents: anchor on their fee per move-in.")
    verify = [q for k, q in offer["verify_on_call"].items() if facts.get(k) in (None, "")]
    return {"tier": tier, "label": t["label"], "guarantee": t["guarantee"], "why": why, "on_call": t.get("on_call", []),
            "verify": verify[:4], "downsells": offer.get("downsells", []) if tier.startswith("full_bed") else []}


KIND_SIGNALS = {"discovery": {"first_call"}, "follow-up": {"follow_up"}, "close": {"close", "follow_up"}}


def pick(table, signals, n, kind=None):
    """Top n rows: a signal about this person counts 2, one that only comes from the call type counts 1,
    an 'always' row counts 0.5. Ties keep the table order (rubric priority)."""
    person = set(signals or [])
    general = KIND_SIGNALS.get(kind, set())
    scored = []
    for i, r in enumerate(table):
        rs = set(r["signals"])
        score = 2 * len(person & rs) + len((general - person) & rs) + (0.5 if "always" in rs else 0)
        if score:
            scored.append((-score, i, r))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in scored[:n]]


DEFAULT_PAGE = {
    "discovery": {
        "qualifying": ["How many beds, how many empty today?", "Private pay or Medicaid beds?",
                       "Could you staff 5 more tours next month?", "Anyone else in this decision?"],
        "timeline": ["How long have those beds been empty?", "What have you tried in that time?",
                     "What has it cost you so far?"],
    },
    "follow-up": {
        "qualifying": ["What changed since we talked?", "Anyone else in this decision now?"],
        "timeline": ["What happened since the last call?", "When do you want the beds full?"],
    },
    "close": {
        "qualifying": ["Still the same number of empty beds?", "Who signs?"],
        "timeline": ["When would you want ads live?", "What would stop a yes today?"],
    },
    "onboarding": {
        "qualifying": ["Agreement signed? Payment in?", "Ad account and page access ready?", "Who on site answers families?"],
        "timeline": ["Go-live date we said out loud?", "Filming this week?"],
    },
}


def skeleton(call, cfg, offer, ghl_ctx=None, priors=None):
    ghl_ctx = ghl_ctx or {"status": "not read"}
    fields = ghl_ctx.get("fields") or {}
    contact = ghl_ctx.get("contact") or {}
    facts = {"total_beds": _int(fields.get("Total Beds")), "empty_beds": None,
             "community_type": fields.get("Community Type") or None, "state": contact.get("state"),
             "uses_placement_agents": None, "staffing_ok": None, "can_fund_ads": None, "operating": None,
             "travel_nurse": None, "below_break_even": None, "rent": None, "decision_makers": None}
    texts = [m.get("body") for m in ghl_ctx.get("messages") or [] if m.get("direction") == "inbound"]
    texts += ghl_ctx.get("notes") or []
    signals = derive_signals(texts)
    if facts["total_beds"] is not None and facts["total_beds"] <= 6:
        signals.append("small_home")
    kind = call["kind"]
    defaults = DEFAULT_PAGE.get(kind, DEFAULT_PAGE["discovery"])
    cold = next((m for m in ghl_ctx.get("messages") or [] if m.get("direction") == "inbound"
                 and "email" in str(m.get("type") or "").lower()), None)
    return {
        "call": call, "home": contact.get("companyName"), "ghl": ghl_ctx, "prior_meetings": priors or [],
        "facts": facts, "signals": sorted(set(signals)), "web_facts": [], "gmail": [],
        "cold_email_reply": {"date": cold["date"], "text": cold["body"]} if cold else None,
        "offer": prescribe(facts, offer),
        "reminders": [r["text"] for r in pick(rules.REMINDERS, signals, 3, kind)],
        "expect": ["%s %s" % (o["says"], o["move"]) for o in pick(rules.EXPECT, signals, 3, kind)],
        "page": {"qualifying": list(defaults["qualifying"]), "suspect_pains": [], "timeline": list(defaults["timeline"]),
                 "wants": [], "other_notes": [], "callout": [], "sources": []},
        "_todo": "Fill facts, signals, web_facts (each {fact, url} or {fact, inferred: true}), gmail, cold_email_reply, "
                 "and every page list. Keep bullets to a few words.",
    }


def gather(calls_doc, cfg, meetings_text=None, use_ghl=False):
    offer = load_offer_rules()
    mlist = mt.parse_list(meetings_text) if meetings_text else []
    access_note = None
    if use_ghl:
        from shared import ghl
        if not ghl.check_access(cfg["ghl"]["hq"]["location"]):
            use_ghl, access_note = False, "Surven HQ GoHighLevel is not readable from this environment"
    out = {"day": calls_doc.get("day"), "notes": list(calls_doc.get("notes") or []), "calls": [], "skipped": []}
    if access_note:
        out["notes"].append(access_note)
    existing = calls_doc.get("existing") or []
    for c in calls_doc.get("calls") or []:
        if c.get("already_prepped"):
            continue
        ctx = ghl_context(c.get("ghl_contact_id"), c.get("email"), cfg) if use_ghl else {"status": "not read"}
        ct = ctx.get("contact") or {}
        if not c.get("name") and (ct.get("firstName") or ct.get("lastName")):
            c["name"] = " ".join(x for x in (ct.get("firstName"), ct.get("lastName")) if x).strip()
            c["first"] = c["name"].split()[0]
            c["page_title"] = "%s Call Prep %s" % (c["name"], c.get("day_token") or "")
            ex = already_prepped(c["first"], _dt.date.fromisoformat(calls_doc["day"]), existing) if calls_doc.get("day") else None
            if ex:
                c["already_prepped"], c["existing_url"] = True, ex.get("url")
                out["skipped"].append(c)
                continue
        if not c.get("email") and ct.get("email"):
            c["email"] = ct["email"]
        pri = mt.prior(mlist, c.get("name"), c.get("email"), before=calls_doc.get("day")) if mlist else []
        out["calls"].append(skeleton(c, cfg, offer, ctx, pri[:5]))
    return out


# ---------------------------------------------------------------- render

LIMITS = {"qualifying": 4, "suspect_pains": 3, "timeline": 3, "wants": 3, "other_notes": 7, "callout": 3}
HEADINGS = [("qualifying", "QUALIFYING"), ("suspect_pains", "SUSPECT PAINS"), ("timeline", "TIMELINE"),
            ("wants", "WANTS"), ("other_notes", "OTHER NOTES")]
DASHES = re.compile(r"[\u2012\u2013\u2014\u2015]")


def _clean(s):
    s = DASHES.sub(", ", str(s or "")).replace("<", "&lt;")
    return " ".join(s.split())


def _words(s):
    return len(re.findall(r"[A-Za-z0-9$']+", re.sub(r"\(https?://[^)]+\)|https?://\S+", "", s or "")))


def compose(item, offer):
    """Final page lists: model text plus the tier, expect and fact lines Python adds."""
    page = item.get("page") or {}
    rx = prescribe(item.get("facts") or {}, offer)
    item["offer"] = rx
    notes = [n for n in page.get("other_notes") or [] if n]
    if not any(n.lower().startswith("tier") for n in notes):
        why = " ".join(rx["why"][:1])
        notes.insert(0, "Tier: %s. %s" % (rx["label"], why) if why else "Tier: %s." % rx["label"])
    if not any(n.lower().startswith("expect") for n in notes) and item.get("expect"):
        notes.append("Expect: " + item["expect"][0])
    for f in (item.get("web_facts") or [])[:2]:
        if isinstance(f, dict) and f.get("fact"):
            if f.get("url"):
                notes.append("Fact: %s ([source](%s))" % (f["fact"], f["url"]))
            elif f.get("inferred"):
                notes.append("Fact: %s (inferred)" % f["fact"])
    callout = [c for c in page.get("callout") or [] if c] or list(item.get("reminders") or [])[:3]
    return {"qualifying": page.get("qualifying") or [], "suspect_pains": page.get("suspect_pains") or [],
            "timeline": page.get("timeline") or [], "wants": page.get("wants") or [], "other_notes": notes,
            "callout": callout, "sources": page.get("sources") or []}


def validate(lists, item):
    hard, warn = [], []
    for key, lim in LIMITS.items():
        vals = lists.get(key) or []
        if not vals:
            hard.append("%s is empty" % key)
        if len(vals) > lim:
            hard.append("%s has %d bullets (max %d)" % (key, len(vals), lim))
        for v in vals:
            n = _words(v)
            if n > 25:
                hard.append("%s bullet is %d words, cut it: %s" % (key, n, v[:60]))
            elif n > 14 and key != "other_notes":
                warn.append("%s bullet is %d words (shorter beats longer): %s" % (key, n, v[:60]))
    for f in item.get("web_facts") or []:
        if isinstance(f, dict) and f.get("fact") and not (f.get("url") or f.get("inferred")):
            hard.append("web fact has no link and is not marked inferred: %s" % f["fact"][:60])
    return hard, warn


def render_md(item, lists, built_at):
    c = item["call"]
    first = c.get("first") or (c.get("name") or "them").split()[0]
    meet = c.get("meet_link")
    head = "<b>MEET LINK:</b> [%s](%s)" % (meet, meet) if meet else "<b>MEET LINK:</b> not on the invite. Check the booking email."
    head += " · %s ET · %s" % (c.get("time_et") or "", (c.get("kind") or "").capitalize())
    parts = [head]
    for key, label in HEADINGS:
        parts.append("<b>%s</b>" % label)
        parts.append("\n".join("- " + _clean(v) for v in lists[key]))
    co = "\n".join("%d. %s" % (i + 1, _clean(v)) for i, v in enumerate(lists["callout"]))
    parts.append('<callout icon="\U0001F534" color="red_bg">\n<b>DO DIFFERENT FOR %s:</b>\n\n%s\n</callout>'
                 % (_clean(first).upper(), co))
    src = []
    rx = item.get("offer") or {}
    src.append("Offer rule: %s. Guarantee: %s" % (rx.get("label"), rx.get("guarantee")))
    for w in rx.get("why", [])[1:]:
        src.append("Why: " + w)
    for q in rx.get("verify", []):
        src.append("Ask on the call: " + q)
    for f in item.get("web_facts") or []:
        if isinstance(f, dict) and f.get("fact"):
            src.append("%s%s" % (f["fact"], " ([source](%s))" % f["url"] if f.get("url") else " (inferred)"))
    for p in item.get("prior_meetings") or []:
        src.append("Earlier call: [%s](%s) %s" % (_clean(p.get("title")), p.get("url"), p.get("date")))
    for g in item.get("gmail") or []:
        if isinstance(g, dict):
            src.append("Email: %s%s" % (_clean(g.get("summary") or g.get("subject")),
                                        " ([thread](%s))" % g["url"] if g.get("url") else ""))
    if item.get("cold_email_reply"):
        cr = item["cold_email_reply"]
        src.append("Their reply %s: \"%s\"" % (cr.get("date", ""), _clean(cr.get("text"))[:200]))
    deals = (item.get("ghl") or {}).get("deals") or []
    for d in deals[:3]:
        src.append("GHL: %s, %s" % (d.get("pipeline"), d.get("stage")))
    src += [_clean(s) for s in lists.get("sources") or []]
    src.append("Built by call_engine %s from: %s." % (built_at, ", ".join(c.get("sources") or [])))
    parts.append("<toggle>\nSources and checks\n\n%s\n</toggle>" % "\n".join("- " + _clean(s) if not s.startswith("- ") else s
                                                                             for s in src))
    return "\n\n".join(parts) + "\n"


def _copy_issues(texts, context="internal"):
    try:
        from tools.copy_check.check import check
    except Exception:  # noqa: BLE001
        return [], ["copy checker missing; ran the dash check only"]
    block, warn = [], []
    for t in texts:
        if not t:
            continue
        r = check(t, context)
        for i in r["issues"]:
            (block if i["severity"] == "block" else warn).append("%s: %s" % (i["rule"], i["match"] or t[:40]))
    return block, warn


def render(prep_doc, out_dir, now=None):
    offer = load_offer_rules()
    os.makedirs(out_dir, exist_ok=True)
    built = et.to_et(now or et.now_utc()).strftime("%Y-%m-%d %I:%M %p ET")
    pages, bad = [], 0
    for item in prep_doc.get("calls") or []:
        lists = compose(item, offer)
        hard, warn = validate(lists, item)
        authored = [v for k in ("qualifying", "suspect_pains", "timeline", "wants", "other_notes", "callout") for v in lists[k]]
        cblock, cwarn = _copy_issues([DASHES.sub(", ", a) for a in authored])
        hard += ["copy: " + x for x in cblock]
        warn += ["copy: " + x for x in cwarn]
        key = item["call"]["key"]
        path = os.path.join(out_dir, key + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_md(item, lists, built))
        pages.append({"key": key, "page_title": item["call"].get("page_title"), "time_et": item["call"].get("time_et"),
                      "kind": item["call"].get("kind"), "first": item["call"].get("first"), "md": path,
                      "ok": not hard, "issues": hard, "warnings": warn[:12]})
        bad += 1 if hard else 0
    doc = {"day": prep_doc.get("day"), "pages": pages, "notes": prep_doc.get("notes") or []}
    with open(os.path.join(out_dir, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return doc, bad


def finish(pages_doc, created, dry_run=False, hidden=None, skipped=None):
    pages = pages_doc.get("pages") or []
    made = [p for p in pages if p["key"] in (created or {})]
    def one(p):
        return "%s %s (%s)" % (p.get("time_et"), p.get("first") or "?", (p.get("kind") or "").capitalize())
    if not pages:
        line = "Call Prep: no new sales calls to prep today."
    elif dry_run:
        ready = [p for p in pages if p.get("ok", True)]
        failing = [p for p in pages if not p.get("ok", True)]
        line = "Call Prep: dry run, %d page(s) ready, nothing written. %s." % (len(ready), "; ".join(one(p) for p in ready) or "none")
        if failing:
            line += " Still failing the format: %s." % "; ".join(one(p) for p in failing)
    else:
        line = "Call Prep: %d call(s), %d page(s) written in Notion Call Prep. %s." % (
            len(pages), len(made), "; ".join(one(p) for p in made) or "none")
        held = [p for p in pages if p["key"] not in (created or {})]
        if held:
            line += " Not written: %s." % "; ".join(one(p) for p in held)
    if skipped:
        line += " Already had a prep page: %s." % "; ".join("%s %s" % (c.get("time_et"), c.get("first") or "?") for c in skipped)
    if hidden:
        line += " %d busy block(s) with hidden titles (%s); check if any is a call." % (
            len(hidden), ", ".join(h["time_et"] for h in hidden))
    sms = None
    if made and not dry_run:
        sms = "Call prep ready in Notion (Call Prep): " + "; ".join(one(p) for p in made) + "."
    return line, sms


# ---------------------------------------------------------------- CLI

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tools.call_engine.prep")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("match")
    m.add_argument("--google", help="Google Calendar events JSON (see module doc)")
    m.add_argument("--ghl", action="store_true", help="also read the Surven HQ GHL calendars (read-only)")
    m.add_argument("--ghl-file", help="test hook: GHL events JSON instead of the API")
    m.add_argument("--day", help="YYYY-MM-DD in Eastern time (default today ET)")
    m.add_argument("--existing", help="Call Prep page fetch text or JSON list of titles")
    m.add_argument("--self-email", action="append", default=[], help="Joey's own addresses to ignore as attendees")
    m.add_argument("--out", default=os.path.join(WORK, "calls.json"))
    g = sub.add_parser("gather")
    g.add_argument("--calls", default=os.path.join(WORK, "calls.json"))
    g.add_argument("--meetings", help="saved Fathom list_meetings text")
    g.add_argument("--ghl", action="store_true")
    g.add_argument("--out", default=os.path.join(WORK, "prep.json"))
    r = sub.add_parser("render")
    r.add_argument("--prep", default=os.path.join(WORK, "prep.json"))
    r.add_argument("--out-dir", default=os.path.join(WORK, "pages"))
    f = sub.add_parser("finish")
    f.add_argument("--pages", default=os.path.join(WORK, "pages", "pages.json"))
    f.add_argument("--calls", default=os.path.join(WORK, "calls.json"))
    f.add_argument("--prep", default=os.path.join(WORK, "prep.json"))
    f.add_argument("--created", default=os.path.join(WORK, "created.json"))
    f.add_argument("--dry-run", action="store_true")
    f.add_argument("--sms", default=os.path.join(WORK, "sms.txt"))
    a = ap.parse_args(argv)
    cfg = load_config()

    if a.cmd == "match":
        day = _dt.date.fromisoformat(a.day) if a.day else et.now_et().date()
        google = json.loads(_read(a.google)) if a.google else {}
        ghl_raw, notes = [], []
        if a.ghl_file:
            d = json.loads(_read(a.ghl_file))
            ghl_raw = d.get("events", d) if isinstance(d, dict) else d
        elif a.ghl:
            ghl_raw, note = ghl_events(day, cfg)
            if note:
                notes.append(note)
        existing = parse_existing(_read(a.existing)) if a.existing else []
        res = match(google, day, cfg, ghl_raw, existing, a.self_email)
        res["notes"] += notes
        _write(a.out, res)
        print(json.dumps({"day": res["day"], "to_prep": [(c["time_et"], c["kind"], c["name"], c["already_prepped"])
                                                          for c in res["calls"]],
                          "not_prepped": res["not_prepped"], "hidden": res["hidden"], "notes": res["notes"],
                          "file": a.out}, indent=1))
        return 0
    if a.cmd == "gather":
        calls = json.loads(_read(a.calls))
        res = gather(calls, cfg, _read(a.meetings) if a.meetings else None, a.ghl)
        _write(a.out, res)
        print("gathered %d call(s) into %s%s%s" % (
            len(res["calls"]), a.out,
            "; already had a prep page: %s" % ", ".join(c.get("first") or "?" for c in res["skipped"]) if res["skipped"] else "",
            "; notes: " + "; ".join(res["notes"]) if res["notes"] else ""))
        return 0
    if a.cmd == "render":
        doc, bad = render(json.loads(_read(a.prep)), a.out_dir)
        for p in doc["pages"]:
            print("%s %s %s" % ("OK" if p["ok"] else "FIX", p["key"], p["md"]))
            for i in p["issues"]:
                print("  must fix: " + i)
            for w in p["warnings"]:
                print("  look at: " + w)
        return 1 if bad else 0
    if a.cmd == "finish":
        pages = json.loads(_read(a.pages)) if os.path.exists(a.pages) else {"pages": []}
        created = json.loads(_read(a.created)) if os.path.exists(a.created) else {}
        calls = json.loads(_read(a.calls)) if os.path.exists(a.calls) else {}
        prep_doc = json.loads(_read(a.prep)) if os.path.exists(a.prep) else {}
        skipped = [c for c in calls.get("calls") or [] if c.get("already_prepped")] + (prep_doc.get("skipped") or [])
        line, sms = finish(pages, created, a.dry_run, calls.get("hidden"), skipped)
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
