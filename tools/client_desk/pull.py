"""Read-only pull of one care-home client's GoHighLevel location for the Client Desk.

  python3 -m tools.client_desk.pull --client agc [--out /tmp/client_desk/agc/raw.json] [--days 45]

Reads (GET, plus the contacts search POST, which is a read): the location (name, city, website), its users (only to
know which contacts are staff), pipelines and stages, contact custom fields, calendars, every contact, every deal,
the tour calendar, every call, text and email of the last --days days (conversation by conversation; the bulk
message export is only a fallback because it drops messages at random), and the call transcripts of unknown
callers. Never writes to GoHighLevel.

Personal data rule: raw.json lives in /tmp only. Even there it holds no phone number and no email address: a phone
becomes its last 4 digits, its area code and short one-way hashes (to spot repeat callers and near-identical numbers),
an email becomes a hash and its domain. Message and transcript text is trimmed and digit runs are masked.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import sys

from shared import ghl, et
from tools.client_desk import metrics as M
from tools.client_desk import profile as prof

LOOKBACK_DAYS = 45
EXPORT_PAGES = 60
TEXT_CHARS = 240
TRANSCRIPT_CHARS = 700
TYPE_BY_NUM = {1: "TYPE_CALL", 2: "TYPE_SMS", 3: "TYPE_EMAIL"}
OPEN_BEDS_SUBJECT = M.OPEN_BEDS_SUBJECT
NO_TRANSCRIPT = re.compile(r"^\s*no transcript", re.I)


# ---------------------------------------------------------------- privacy helpers

def hkey(s):
    return hashlib.sha256(("client_desk:" + str(s)).encode("utf-8")).hexdigest()[:16]


def phone_digits(p):
    if not isinstance(p, str):
        return ""
    d = re.sub(r"\D", "", p)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d


def phone_info(p):
    d = phone_digits(p)
    if len(d) < 7:
        return None
    nanp = len(d) == 10
    return {"last4": d[-4:], "area": d[:3] if nanp else "", "key": hkey(d),
            "block8": hkey("b8:" + d[:8]) if nanp else "", "block6": hkey("b6:" + d[:6]) if nanp else ""}


def norm_email(e):
    e = (e or "").strip().lower() if isinstance(e, str) else ""
    if "@" not in e:
        return ""
    local, dom = e.split("@", 1)
    return local.split("+", 1)[0] + "@" + dom


def email_info(e):
    n = norm_email(e)
    return {"key": hkey(n), "domain": n.split("@", 1)[1]} if n else None


_NUM = re.compile(r"\+?\(?\d[\d\-\s().]{5,}\d")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask(text, limit=TEXT_CHARS):
    """Plain text, no HTML, digit runs and email addresses masked, trimmed."""
    if not text:
        return ""
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", str(text))
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    t = _MAIL.sub("[email]", t)
    t = _NUM.sub("[number]", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit].rstrip() + ("..." if len(t) > limit else "")


def domain_of(url):
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/:?#]+)", (url or "").strip().lower())
    return m.group(1) if m else ""


# ---------------------------------------------------------------- slimming

REAL_NAME_BAD = re.compile(r"^(caller|unknown|wireless caller|anonymous|no name|restricted|private|"
                           r"spam|potential spam|scam likely|telemarketer|toll free|v\d+)\b", re.I)


def real_name(first, last):
    """True when the record carries a person's name, not a number or a placeholder like 'Caller 1234'."""
    for part in (first, last):
        s = (part or "").strip()
        if not s:
            continue
        if re.search(r"\d", s) or "@" in s or REAL_NAME_BAD.match(s):
            continue
        if re.search(r"[A-Za-z]{2,}", s):
            return True
    return False


def slim_contact(c, field_ids):
    vals = {}
    for f in c.get("customFields") or c.get("customField") or []:
        v = f.get("value", f.get("field_value"))
        if v in (None, "", []):
            continue
        vals[f.get("id")] = ", ".join(str(x) for x in v) if isinstance(v, list) else v
    fields = {}
    for role, fid in field_ids.items():
        if fid in vals:
            v = vals[fid]
            fields[role] = mask(v, 300) if role in ("whisper", "last_transcript") else (
                v if isinstance(v, (int, float)) else str(v)[:200])
    first, last = (c.get("firstName") or "").strip(), (c.get("lastName") or "").strip()
    return {
        "id": c.get("id"),
        "first": first if real_name(first, "") else "",
        "last_initial": last[:1].upper() if real_name("", last) else "",
        "named": real_name(first, last),
        "name_test": bool(re.search(r"\btest\b", (first + " " + last).lower())),
        "company": (c.get("companyName") or "").strip()[:120],
        "tags": sorted({str(t).strip().lower() for t in c.get("tags") or []}),
        "dnd": bool(c.get("dnd")),
        "added": c.get("dateAdded"),
        "source": (c.get("source") or "")[:80],
        "phone": phone_info(c.get("phone")),
        "email": email_info(c.get("email")),
        "fields": fields,
    }


def slim_opp(o):
    c = o.get("contact") or {}
    return {
        "id": o.get("id"), "contactId": o.get("contactId") or c.get("id"), "pipelineId": o.get("pipelineId"),
        "stageId": o.get("pipelineStageId"), "status": o.get("status"), "created": o.get("createdAt"),
        "stage_changed": o.get("lastStageChangeAt"), "status_changed": o.get("lastStatusChangeAt"),
        "updated": o.get("updatedAt"), "name": (o.get("name") or "")[:120], "company": (c.get("companyName") or "")[:120],
    }


def slim_event(e):
    return {
        "id": e.get("id"), "contactId": e.get("contactId"), "calendarId": e.get("calendarId"),
        "start": e.get("startTime"), "end": e.get("endTime"), "added": e.get("dateAdded"),
        "status": (e.get("appointmentStatus") or e.get("appoinmentStatus") or "").lower(),
        "deleted": bool(e.get("deleted")), "source": ((e.get("createdBy") or {}).get("source") or "").lower(),
    }


def slim_message(m):
    meta = m.get("meta") or {}
    call = meta.get("call") or {}
    typ = m.get("messageType") or TYPE_BY_NUM.get(m.get("type")) or ""
    d = {
        "id": m.get("id"), "cid": m.get("contactId"), "conv": m.get("conversationId"), "type": typ,
        "dir": (m.get("direction") or "").lower(), "src": (m.get("source") or "").lower(),
        "status": (m.get("status") or "").lower(), "when": m.get("dateAdded"),
        "user": bool(m.get("userId")),
    }
    if "CALL" in typ:
        d["dur"] = call.get("duration")
        d["cst"] = (call.get("status") or m.get("status") or "").lower()
        d["rec"] = any("ecording" in str(a) for a in m.get("attachments") or [])
    if typ.endswith("EMAIL"):
        subj = m.get("subject") or (meta.get("email") or {}).get("subject") or ""
        d["subj"] = mask(subj, 120)
    if d["dir"] == "inbound" and typ in ("TYPE_SMS", "TYPE_EMAIL", "TYPE_LIVE_CHAT", "TYPE_WEBCHAT"):
        d["text"] = mask(m.get("body"))
    return d


def transcript_summary(r):
    """GHL transcription answer (a list of sentences, or an error) -> short summary."""
    if not isinstance(r, list):
        return {"status": "error" if isinstance(r, dict) and r.get("error") not in (404,) else "none",
                "segments": 0, "text": "", "channels": {}}
    lines, chans = [], {}
    for s in r:
        t = (s.get("transcript") or "").strip()
        if not t or NO_TRANSCRIPT.match(t):
            continue
        ch = str(s.get("mediaChannel") if s.get("mediaChannel") is not None else "?")
        chans[ch] = chans.get(ch, 0) + 1
        lines.append((ch, t))
    text = " | ".join("%s: %s" % (c, t) for c, t in lines)
    return {"status": "ok" if lines else "none", "segments": len(lines), "text": mask(text, TRANSCRIPT_CHARS),
            "channels": chans}


def maybe_unknown_caller(c):
    """The pull-time test for a contact the triage may show (metrics.classify makes the final call)."""
    tags = set(c.get("tags") or [])
    stage = str((c.get("fields") or {}).get("agent_stage") or "").strip().lower()
    return (not c.get("named") and not c.get("name_test") and stage in ("", "new")
            and not (tags & M.INTERNAL_TAGS) and "referral-partner" not in tags
            and not any(t.startswith("partner-") for t in tags))


# ---------------------------------------------------------------- discovery

def pick_by_name(items, want, label="name"):
    """want = {"id": x or None, "match": [words], "fallback_id": y}. Returns (id, name, how)."""
    by_id = {i.get("id"): i for i in items}
    if want.get("id"):
        hit = by_id.get(want["id"])
        return want["id"], (hit or {}).get(label, ""), "config id" + ("" if hit else " (not seen in the list)")
    for word in want.get("match") or []:
        cands = [i for i in items if word.lower() in (i.get(label) or "").lower() and i.get("isActive", True) is not False]
        if cands:
            cands.sort(key=lambda i: (len(i.get(label) or ""), i.get(label) or ""))
            return cands[0].get("id"), cands[0].get(label), "found by name"
    fb = want.get("fallback_id")
    if fb:
        return fb, (by_id.get(fb) or {}).get(label, ""), "fallback id"
    return None, "", "none"


def resolve_fields(cf_list, p):
    names = {}
    for f in cf_list or []:
        names.setdefault((f.get("name") or "").strip().lower(), f.get("id"))
    out = dict(p["fields"])
    for role, wanted in p["field_names"].items():
        for n in wanted:
            fid = names.get(n.lower())
            if fid:
                out[role] = fid
                break
        else:
            if role not in out:
                for n in wanted:
                    hit = next((fid for nm, fid in names.items() if nm.startswith(n.lower())), None)
                    if hit:
                        out[role] = hit
                        break
    return out


# ---------------------------------------------------------------- reads

def export_messages(loc, start, end, channel=None, log=None, tries=3):
    """Every message in the window, following nextCursor. The export can hand back a short page in the middle, so
    the loop never stops on a short page; it checks the count against the API's own total and pulls again (up to
    `tries` times) when it comes up short. Returns (messages, error or None)."""
    best, err, total = [], None, None
    for attempt in range(tries):
        params = {"locationId": loc, "limit": 100, "startDate": start, "endDate": end}
        if channel:
            params["channel"] = channel
        got, err = {}, None
        for _ in range(EXPORT_PAGES):
            r = ghl.call("/conversations/messages/export", params, ver=ghl.V_CONV)
            if not ghl.ok(r):
                err = r
                break
            batch = r.get("messages") or []
            if isinstance(r.get("total"), int):
                total = r["total"]
            for m in batch:
                if m.get("id"):
                    got[m["id"]] = m
            cur = r.get("nextCursor")
            if not cur or not batch:
                break
            params["cursor"] = cur
        if len(got) > len(best):
            best = list(got.values())
        if err is None and (total is None or len(best) >= total):
            return best, None
        if log:
            log("message export %s came back short (%d of %s), pulling again" % (channel or "calls+texts", len(best), total))
    return best, err or {"error": "short", "body": "got %d of %s messages" % (len(best), total)}


def export_union(loc, start, end, channel=None, log=None, max_passes=3):
    """The export endpoint sometimes answers the same question with fewer messages, and then reports that smaller
    number as its total too (seen live 2026-11-02: 696 or 770 for one window). So pull it at least twice and keep
    the union by id; pull a third time only if the second pass found anything new. Returns (messages, error, sizes)."""
    union, sizes, err = {}, [], None
    for i in range(max_passes):
        got, e = export_messages(loc, start, end, channel, log, tries=2)
        if e is not None:
            err = e
        before = len(union)
        for m in got:
            union[m["id"]] = m
        sizes.append(len(got))
        if i >= 1 and len(union) == before:
            break
        if i >= 1 and log:
            log("message export %s: pass %d found %d more" % (channel or "calls+texts", i + 1, len(union) - before))
    if union and err is not None and err.get("error") == "short":
        err = None                         # a short pass that the union already covered is not an error
    return list(union.values()), err, sizes


def _ms(v):
    """A conversation's lastMessageDate (epoch ms, or an ISO string) as epoch ms; 0 when missing."""
    t = et.parse(v)
    return t.timestamp() * 1000 if t else 0


def conversation_messages(loc, start, skip_contacts=(), workers=3, log=None):
    """Every message since `start` (aware UTC), read conversation by conversation: the same API the AGC collector and
    the planners use, and the one that has proved complete. Conversations whose newest message is older than `start`
    are skipped, each thread stops paging once it passes `start`, and `skip_contacts` (Joey's alert contacts, which
    carry hundreds of planner texts) are never read. Returns (messages, error or None, number of conversations read)."""
    start_ms = start.timestamp() * 1000
    params = {"locationId": loc, "limit": 100, "sort": "desc", "sortBy": "last_message_date"}
    convs = []
    for _ in range(40):
        r = ghl.call("/conversations/search", params, ver=ghl.V_CONV)
        if not ghl.ok(r):
            return None, r, 0
        batch = r.get("conversations") or []
        convs += batch
        if len(batch) < params["limit"]:
            break
        last = batch[-1]
        if _ms(last.get("lastMessageDate")) < start_ms:
            break
        sa = last.get("sort")
        nxt = sa[0] if isinstance(sa, list) and sa else last.get("lastMessageDate")
        if not nxt or nxt == params.get("startAfterDate"):
            break                              # no cursor, or the same page again: stop rather than loop
        params["startAfterDate"] = nxt
    skip = set(skip_contacts or ())
    want, seen = [], set()
    for cv in convs:
        if cv.get("id") in seen or _ms(cv.get("lastMessageDate")) < start_ms or cv.get("contactId") in skip:
            continue
        seen.add(cv.get("id"))
        want.append(cv)

    def one(cv):
        out, q = [], {"limit": 100}
        for _ in range(30):
            r = ghl.call("/conversations/%s/messages" % cv["id"], q, ver=ghl.V_CONV)
            if not ghl.ok(r):
                return out, r
            box = r.get("messages") or {}
            batch = box.get("messages") or []
            for m in batch:
                m.setdefault("contactId", cv.get("contactId"))
                m.setdefault("conversationId", cv.get("id"))
            out += batch
            oldest = min((et.parse(m.get("dateAdded")) for m in batch if et.parse(m.get("dateAdded"))), default=None)
            if not box.get("nextPage") or not batch or (oldest is not None and oldest < start):
                break
            q = {"limit": 100, "lastMessageId": box.get("lastMessageId") or batch[-1].get("id")}
        return out, None

    msgs, err = [], None
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for got, e in ex.map(one, want):
            msgs += got
            if e is not None:
                err = e
    # An email and its reply come back as ONE thread row carrying several email ids (and sometimes no direction),
    # so the outbound send hides inside the reply. Expand those rows through the single-email endpoint.
    fold = [m for m in msgs if (m.get("messageType") == "TYPE_EMAIL" or m.get("type") == 3)
            and (len(((m.get("meta") or {}).get("email") or {}).get("messageIds") or []) > 1 or not m.get("direction"))
            and ((m.get("meta") or {}).get("email") or {}).get("messageIds")]
    if fold:
        jobs = [(m, eid) for m in fold for eid in m["meta"]["email"]["messageIds"]]

        def email(job):
            m, eid = job
            r = ghl.call("/conversations/messages/email/" + eid, ver=ghl.V_CONV)
            e = r.get("emailMessage", r) if ghl.ok(r) else None
            if not e:
                return m, None
            return m, {"id": "email:" + eid, "contactId": e.get("contactId") or m.get("contactId"),
                       "conversationId": m.get("conversationId"), "messageType": "TYPE_EMAIL",
                       "direction": e.get("direction") or "", "dateAdded": e.get("dateAdded") or m.get("dateAdded"),
                       "status": e.get("status"), "source": e.get("source") or m.get("source"),
                       "subject": e.get("subject"), "body": e.get("body"), "userId": m.get("userId")}

        expanded, failed = [], set()
        with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for m, one_email in ex.map(email, jobs):
                if one_email is None:
                    failed.add(id(m))
                else:
                    expanded.append(one_email)
        drop = {id(m) for m in fold if id(m) not in failed}
        msgs = [m for m in msgs if id(m) not in drop] + expanded
    msgs = [m for m in msgs if (et.parse(m.get("dateAdded")) or start) >= start]
    if log:
        log("read %d conversations with activity since %s" % (len(want), start.date().isoformat()))
    return msgs, err, len(want)


def iso_z(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def pull(p, now=None, days=LOOKBACK_DAYS, log=None, workers=3):
    log = log or (lambda *_: None)
    now = now or et.now_utc()
    loc = p["location"]
    raw = {"pulled_at": now.isoformat(), "client": p["key"], "location_id": loc, "days": days, "errors": [],
           "location": {}, "internal": {"phones": [], "emails": [], "domains": list(p["internal_domains"]),
                                        "home_block6": "", "home_phone_key": ""},
           "pipelines": [], "family_pipeline_id": None, "partner_pipeline_id": None, "tour_calendar_id": None,
           "discovery": {}, "field_ids": {}, "contacts": [], "opportunities": [], "tour_events": [],
           "messages": [], "transcripts": {}, "open_beds_last": None}
    err = raw["errors"]
    if not ghl.check_access(loc):
        raw["fatal"] = "no access: this environment's GoHighLevel key does not read location " + loc
        return raw

    # location (name, city, website only) and the numbers and inboxes that are the home's own
    r = ghl.call("/locations/" + loc)
    L = (r.get("location") or r) if ghl.ok(r) else {}
    if not ghl.ok(r):
        err.append(["location", str(r)[:160]])
    raw["location"] = {"name": (L.get("name") or "").strip(), "city": (L.get("city") or "").strip(),
                       "state": (L.get("state") or "").strip(), "website": (L.get("website") or "").strip(),
                       "timezone": L.get("timezone") or "", "has_phone": bool(L.get("phone"))}
    phones, emails = set(), set()
    lp = phone_info(L.get("phone"))
    if lp:
        phones.add(lp["key"])
        raw["internal"]["home_block6"] = lp["block6"]
        raw["internal"]["home_phone_key"] = lp["key"]
    le = email_info(L.get("email"))
    if le:
        emails.add(le["key"])
    site = domain_of(L.get("website"))
    if site:
        raw["internal"]["domains"] = sorted(set(raw["internal"]["domains"]) | {site})

    u = ghl.call("/users/", {"locationId": loc})
    if ghl.ok(u):
        for x in u.get("users") or []:
            cand = [x.get("phone")]
            if isinstance(x.get("lcPhone"), dict):
                cand += [v for v in x["lcPhone"].values() if isinstance(v, str)]
            for ph in cand:
                pi = phone_info(ph)
                if pi:
                    phones.add(pi["key"])
            ei = email_info(x.get("email"))
            if ei:
                emails.add(ei["key"])
    else:
        err.append(["users", str(u)[:160]])
    raw["internal"]["phones"], raw["internal"]["emails"] = sorted(phones), sorted(emails)

    # pipelines and stages
    pls = ghl.pipelines(loc)
    if isinstance(pls, list):
        raw["pipelines"] = [{"id": x.get("id"), "name": x.get("name") or "",
                             "stages": [{"id": s.get("id"), "name": s.get("name") or ""} for s in x.get("stages") or []]}
                            for x in pls]
    else:
        err.append(["pipelines", str(pls)[:160]])
    fid, fname, fhow = pick_by_name(raw["pipelines"], p["family_pipeline"])
    pid, pname, phow = pick_by_name([x for x in raw["pipelines"] if x["id"] != fid], p["partner_pipeline"]) \
        if p["partner_pipeline"] else (None, "", "none")
    raw["family_pipeline_id"], raw["partner_pipeline_id"] = fid, pid
    raw["discovery"]["family_pipeline"] = {"id": fid, "name": fname, "how": fhow}
    raw["discovery"]["partner_pipeline"] = {"id": pid, "name": pname, "how": phow}

    # fields
    cf_list = ghl.custom_fields(loc)
    if not isinstance(cf_list, list):
        err.append(["customFields", str(cf_list)[:160]])
        cf_list = []
    raw["field_ids"] = resolve_fields(cf_list, p)

    # calendars
    cals = ghl.call("/calendars/", {"locationId": loc}, ver=ghl.V_CONV)
    cal_list = [{"id": c.get("id"), "name": c.get("name") or "", "isActive": c.get("isActive", True)}
                for c in (cals.get("calendars") or [])] if ghl.ok(cals) else []
    if not ghl.ok(cals):
        err.append(["calendars", str(cals)[:160]])
    tid, tname, thow = pick_by_name(cal_list, p["tour_calendar"])
    raw["tour_calendar_id"] = tid
    raw["discovery"]["tour_calendar"] = {"id": tid, "name": tname, "how": thow}

    # contacts and deals
    cs = ghl.search_contacts(loc)
    if isinstance(cs, list):
        raw["contacts"] = [slim_contact(c, raw["field_ids"]) for c in cs if c.get("id")]
    else:
        err.append(["contacts", str(cs)[:160]])
        raw["fatal"] = "could not read contacts"
        return raw
    opps = ghl.opportunities(loc)
    if isinstance(opps, list):
        raw["opportunities"] = [slim_opp(o) for o in opps]
    else:
        err.append(["opportunities", str(opps)[:160]])
    log("%d contacts, %d deals" % (len(raw["contacts"]), len(raw["opportunities"])))

    # tour calendar
    if tid:
        since = et.parse(p["since"]) or (now - dt.timedelta(days=120))
        ev = ghl.calendar_events(loc, tid, since.timestamp() * 1000, (now + dt.timedelta(days=30)).timestamp() * 1000)
        if isinstance(ev, list):
            raw["tour_events"] = [slim_event(e) for e in ev if not e.get("calendarId") or e.get("calendarId") == tid]
        else:
            err.append(["tour_calendar", str(ev)[:160]])

    # messages: every call, text and email of the window, conversation by conversation. The bulk export endpoint
    # is only the fallback: live it answered the same question with 696 or 770 messages, and 8 or 55 emails.
    since_dt = now - dt.timedelta(days=days)
    seen, msgs = set(), []
    raw["message_source"] = "conversations"
    batch, e, nconv = conversation_messages(loc, since_dt, p.get("internal_contacts"), workers, log)
    raw["conversations_read"] = nconv
    if batch is None:
        err.append(["conversations", str(e)[:160]])
        raw["message_source"] = "export (fallback)"
        batch = []
        start, end = iso_z(since_dt), iso_z(now + dt.timedelta(minutes=5))
        for ch in (None, "Email"):
            got, e2, _ = export_union(loc, start, end, ch, log)
            if e2 is not None:
                err.append(["messages:" + (ch or "calls+texts"), str(e2)[:160]])
            batch += got
    elif e is not None:
        err.append(["messages", str(e)[:160]])
    for m in batch:
        if m.get("id") and m["id"] not in seen:
            seen.add(m["id"])
            sm = slim_message(m)
            if not sm["type"].startswith("TYPE_ACTIVITY"):
                msgs.append(sm)
    msgs.sort(key=lambda m: str(m.get("when") or ""))
    raw["messages"] = msgs
    log("%d messages in the last %d days" % (len(msgs), days))

    # the last open-beds email (subject and send date only)
    ob = [m for m in msgs if m["type"] == "TYPE_EMAIL" and m["dir"] == "outbound" and OPEN_BEDS_SUBJECT.search(m.get("subj") or "")]
    if ob:
        last = ob[-1]
        day = (last.get("when") or "")[:10]
        same = [m for m in ob if (m.get("when") or "")[:10] == day]   # every subject variant sent that day
        subjects = []
        for m in same:
            if m.get("subj") and m["subj"] not in subjects:
                subjects.append(m["subj"])
        raw["open_beds_last"] = {"subject": last.get("subj"), "subjects": subjects, "when": last.get("when"),
                                 "recipients": len({m["cid"] for m in same}),
                                 "contact_ids": sorted({m["cid"] for m in same if m.get("cid")})}

    # transcripts for calls from likely unknown callers only: no real name, not judged yet by the planner, and not a
    # partner or an internal record. Partners and judged contacts never reach the triage, so reading theirs would
    # only use up the cap (live: 33 of 40 reads went to contacts the triage never shows).
    unnamed = {c["id"] for c in raw["contacts"] if maybe_unknown_caller(c)}
    cutoff = now - dt.timedelta(days=days)
    want = [m for m in msgs if "CALL" in m["type"] and m["dir"] == "inbound" and m["cid"] in unnamed
            and (et.parse(m["when"]) or now) >= cutoff and (m.get("rec") or (m.get("dur") or 0) > 0)]
    want = want[-40:]

    def one(m):
        r2 = ghl.call("/conversations/locations/%s/messages/%s/transcription" % (loc, m["id"]), ver=ghl.V_CONV)
        return m["id"], transcript_summary(r2)

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for mid, summ in ex.map(one, want):
            raw["transcripts"][mid] = summ
    log("%d call transcripts read" % len(raw["transcripts"]))
    return raw


def write_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Client Desk read-only pull.")
    ap.add_argument("--client", required=True)
    ap.add_argument("--out")
    ap.add_argument("--days", type=int, default=LOOKBACK_DAYS)
    a = ap.parse_args(argv)
    p = prof.load(a.client)
    raw = pull(p, days=a.days, log=lambda s: print("pull: " + s, file=sys.stderr))
    out = a.out or os.path.join(p["out_dir"], "raw.json")
    write_json(out, raw)
    print("%s: %d contacts, %d deals, %d messages, %d errors -> %s" % (
        p["short"], len(raw["contacts"]), len(raw["opportunities"]), len(raw["messages"]), len(raw["errors"]), out))
    if raw.get("fatal"):
        print("NO ACCESS: " + raw["fatal"])
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
