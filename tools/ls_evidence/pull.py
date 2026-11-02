"""Read-only, bounded pull of the Lead Suite evidence from one GoHighLevel location.

  python3 -m tools.ls_evidence.pull [--location hq] [--out /tmp/ls_evidence/raw.json] [--max-leads 250]

Reads: the contact custom field list (to find the STL fields by name), the Leadsuite Pipeline and its deals, every
contact tagged leadsuite, and for each lead since ads went live: its conversations and every message time stamp
(calls with status and direction, texts and emails in and out; never message text), plus the Discovery Call and Lead
Suite calendars. For leads with a booked call it also reads their GHL notes and the length of their answered calls
(from the call record, else the transcript's word count, never the words). Never writes to GHL.
Phone numbers and emails are never kept: duplicates are found with a one-way hash.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys

from shared import ghl, et
from tools.ls_evidence import profile as prof
from tools.ls_evidence import score as score_mod

WORKERS = 3             # GHL allows about 100 requests in 10 s per location, shared with the listener
CONVS_PER_CONTACT = 3
MSG_PAGES = 5           # 100 messages a page, per conversation, newest first
OPP_PAGES = 5
CONTACT_PAGES = 20
MAX_CALL_DETAILS = 150
MAX_NOTES_CONTACTS = 120
NOTE_CHARS = 900
CALL_TYPES = {"TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_IVR_CALL"}
TYPE_BY_NUM = {1: "TYPE_CALL", 2: "TYPE_SMS", 3: "TYPE_EMAIL", 8: "TYPE_CAMPAIGN_CALL", 28: "TYPE_ACTIVITY_OPPORTUNITY"}
CONTACT_LIKE = re.compile(r"@|\d{3}[\s.-]?\d{3}[\s.-]?\d{4}")
TEST_NAMES = {"test", "test test", "test test test", "joey", "joseph gargiulo", "jake kindall"}
AUTO_REPLY_RX = re.compile(r"out of (the )?office|automatic reply|auto-?reply|autoreply|undeliverable|delivery status", re.I)
OPT_OUT_RX = re.compile(r"^\s*(stop|stop all|unsubscribe|end|quit|remove me)\s*[.!]*\s*$", re.I)


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()[:10]


def dup_keys(c):
    """One-way keys for the duplicate check. The phone and email themselves are never kept."""
    keys = []
    digits = re.sub(r"\D", "", str(c.get("phone") or ""))[-10:]
    if len(digits) == 10:
        keys.append("p" + _h(digits))
    em = str(c.get("email") or "").strip().lower()
    if "@" in em:
        keys.append("e" + _h(em))
    return keys


def first_name(c):
    for v in (c.get("firstName"), (c.get("contactName") or "").split(" ")[0]):
        v = str(v or "").strip()
        if v and not CONTACT_LIKE.search(v):
            return v[:1].upper() + v[1:]
    return ""


def slim_contact(c, field_ids):
    by_id = {}
    for f in c.get("customFields") or c.get("customField") or []:
        v = f.get("value", f.get("field_value"))
        if v not in (None, "", []):
            by_id[f.get("id")] = v
    fields = {role: by_id[fid] for role, fid in field_ids.items() if fid in by_id}
    full = " ".join(str(c.get(k) or "").strip() for k in ("firstName", "lastName")).strip().lower()
    return {
        "id": c.get("id"),
        "first": first_name(c),
        "test_name": full in TEST_NAMES or full.startswith("test "),
        "tags": [str(t) for t in (c.get("tags") or [])],
        "dateAdded": c.get("dateAdded"),
        "timezone": c.get("timezone") or "",
        "dnd": bool(c.get("dnd")),
        "fields": fields,
        "dup": dup_keys(c),
    }


def slim_message(m):
    meta = m.get("meta") or {}
    em = meta.get("email") or {}
    call = meta.get("call") or {}
    typ = m.get("messageType") or TYPE_BY_NUM.get(m.get("type")) or ""
    d = {"id": m.get("id"), "when": m.get("dateAdded"), "dir": m.get("direction") or em.get("direction"),
         "type": typ, "source": m.get("source"), "status": m.get("status") or call.get("status")}
    if typ in CALL_TYPES:
        if call.get("duration") is not None:
            d["duration"] = call.get("duration")
        if call.get("status"):
            d["call_status"] = call.get("status")
    if typ == "TYPE_EMAIL" and em.get("subject"):
        d["subject"] = re.sub(r"\s+", " ", html.unescape(str(em.get("subject"))))[:140]
    if d["dir"] == "inbound" and typ in ("TYPE_EMAIL", "TYPE_SMS"):
        body = re.sub(r"<[^>]+>", " ", str(m.get("body") or ""))
        if AUTO_REPLY_RX.search(body + " " + str(em.get("subject") or "")):
            d["auto"] = True
        if OPT_OUT_RX.match(body.strip()):
            d["stop"] = True
    return d


def read_messages(loc, cid):
    """{msgs, ok, truncated, oldest} for one contact, newest page last. Never raises."""
    block = {"msgs": [], "ok": True, "truncated": False, "convs": 0}
    errors = []
    convs = ghl.conversations(loc, contact_id=cid, limit=10)
    if not isinstance(convs, list):
        block["ok"] = False
        return block, [["conversations", cid, str(convs)[:160]]]
    convs = [x for x in convs if x.get("contactId") in (None, cid)]
    convs.sort(key=lambda x: x.get("lastMessageDate") or 0, reverse=True)
    if len(convs) > CONVS_PER_CONTACT:
        block["truncated"] = True
    for cv in convs[:CONVS_PER_CONTACT]:
        block["convs"] += 1
        got = ghl.messages(cv["id"], max_pages=MSG_PAGES)
        if not isinstance(got, list):
            block["ok"] = False
            errors.append(["messages", cv.get("id"), str(got)[:160]])
            continue
        if len(got) >= 100 * MSG_PAGES:
            block["truncated"] = True
        block["msgs"] += [slim_message(m) for m in got if m.get("contactId") in (None, cid)]
    seen, uniq = set(), []
    for m in sorted(block["msgs"], key=lambda x: str(x.get("when") or "")):
        if m["id"] not in seen:
            seen.add(m["id"])
            uniq.append(m)
    block["msgs"] = uniq
    block["oldest"] = uniq[0]["when"] if uniq else None
    return block, errors


def call_detail(loc, m):
    """{'duration': s or None, 'words': n or None} for one answered call."""
    out = {"duration": None, "words": None}
    if m.get("type") == "TYPE_CALL":
        r = ghl.call(f"/conversations/messages/{m['id']}", ver=ghl.V_CONV)
        if ghl.ok(r):
            mm = r.get("message", r)
            out["duration"] = ((mm.get("meta") or {}).get("call") or {}).get("duration")
            if out["duration"] is not None:
                return out
    t = ghl.call(f"/conversations/locations/{loc}/messages/{m['id']}/transcription", ver=ghl.V_CONV)
    if isinstance(t, list):
        out["words"] = sum(len(str(x.get("transcript") or "").split()) for x in t if isinstance(x, dict))
    return out


def slim_note(n):
    text = n.get("bodyText") or re.sub(r"<[^>]+>", " ", html.unescape(str(n.get("body") or "")))
    return {"when": n.get("dateAdded"), "text": re.sub(r"\s+", " ", str(text)).strip()[:NOTE_CHARS]}


def title_kind(title, s_calls):
    t = str(title or "")
    if re.search(s_calls.get("client_call_title_rx") or r"$^", t, re.I):
        return "client"
    if re.search(s_calls.get("lead_suite_title_rx") or "discovery", t, re.I):
        return "discovery"
    return "other"


def ms(d):
    return int(d.timestamp() * 1000)


def pull(p, settings, now=None, max_leads=250, workers=WORKERS, probe=0, log=None):
    log = log or (lambda *_: None)
    now = now or et.now_utc()
    loc = p["location"]
    live = score_mod.live_start_utc(settings)
    raw = {"pulled_at": now.isoformat(), "location_key": p["key"], "location_id": loc, "probe": bool(probe),
           "joey_contact": p.get("joey_contact"), "stages": {}, "field_ids": {}, "field_how": {},
           "leads": {}, "messages": {}, "call_details": {}, "notes": {}, "events": [], "errors": [],
           "bounds": {"max_leads": max_leads}, "counts": {}}
    errors = raw["errors"]
    if not ghl.check_access(loc):
        raw["fatal"] = "no access: this environment's GHL key does not read location " + loc
        return raw

    cf_list = ghl.custom_fields(loc)
    if not isinstance(cf_list, list):
        errors.append(["customFields", str(cf_list)[:160]])
    raw["field_ids"], raw["field_how"] = prof.resolve_fields(cf_list if isinstance(cf_list, list) else None)
    fids = raw["field_ids"]

    # the Leadsuite Pipeline: stage names and every deal
    opps_by_contact = {}
    if p.get("pipeline"):
        pls = ghl.pipelines(loc)
        if isinstance(pls, list):
            for x in pls:
                if x.get("id") == p["pipeline"]:
                    raw["stages"] = {s.get("id"): s.get("name") for s in x.get("stages") or []}
        else:
            errors.append(["pipelines", str(pls)[:160]])
        r = ghl.opportunities(loc, p["pipeline"], status="all", max_pages=OPP_PAGES)
        if isinstance(r, list):
            for o in r:
                if o.get("pipelineId") not in (None, p["pipeline"]):
                    continue
                cid = o.get("contactId") or (o.get("contact") or {}).get("id")
                if not cid:
                    continue
                lst = opps_by_contact.setdefault(cid, [])
                if all(x["id"] != o.get("id") for x in lst):
                    lst.append({"id": o.get("id"), "stageId": o.get("pipelineStageId"), "status": o.get("status"),
                                "createdAt": o.get("createdAt"), "updatedAt": o.get("updatedAt")})
        else:
            errors.append(["opportunities", str(r)[:160]])
    raw["counts"]["pipeline_deals"] = sum(len(v) for v in opps_by_contact.values())

    # the sales calendars, from a week before ads went live to 30 days ahead
    s_calls = settings.get("calls") or {}
    for kind, cal in (p.get("calendars") or {}).items():
        evs = ghl.calendar_events(loc, cal, ms(live - dt.timedelta(days=7)), ms(now + dt.timedelta(days=30)))
        if not isinstance(evs, list):
            errors.append(["events", kind, str(evs)[:160]])
            continue
        for e in evs:
            if e.get("calendarId") not in (None, cal):
                continue
            raw["events"].append({
                "id": e.get("id"), "cal": kind, "contactId": e.get("contactId"),
                "start": e.get("startTime"), "end": e.get("endTime"), "booked_at": e.get("dateAdded"),
                "status": str(e.get("appointmentStatus") or e.get("appoinmentStatus") or e.get("status") or "").lower(),
                "deleted": bool(e.get("deleted")), "title_kind": title_kind(e.get("title"), s_calls),
                "source": (e.get("createdBy") or {}).get("source") or ""})
    log(f"calendar events: {len(raw['events'])}")

    # every contact with the leadsuite tag (filtered search; a full scan if the filter is refused)
    tag = p.get("tag") or prof.LEAD_TAG
    found = ghl.search_contacts(loc, filters=[{"field": "tags", "operator": "eq", "value": tag}],
                                max_pages=CONTACT_PAGES)
    if not isinstance(found, list):
        errors.append(["contacts search (tag filter)", str(found)[:160]])
        found = ghl.search_contacts(loc, max_pages=CONTACT_PAGES)
        if not isinstance(found, list):
            errors.append(["contacts search", str(found)[:160]])
            found = []
    contacts = {c["id"]: c for c in found if c.get("id") and tag in [str(t).lower() for t in c.get("tags") or []]}
    if probe:   # build-time smoke test on another location only: score the newest contacts as if they were leads
        r = ghl.call("/contacts/search", method="POST", body={"locationId": loc, "pageLimit": int(probe), "page": 1})
        for c in (r.get("contacts") or [])[:int(probe)] if ghl.ok(r) else []:
            contacts.setdefault(c["id"], c)
        for cid in dict.fromkeys(e["contactId"] for e in raw["events"] if e.get("contactId")):
            if cid not in contacts:
                c = ghl.contact(cid)
                if ghl.ok(c) and c.get("id"):
                    contacts[cid] = c
    for cid in opps_by_contact:
        if cid not in contacts:
            c = ghl.contact(cid)
            if ghl.ok(c) and c.get("id"):
                contacts[cid] = c
            else:
                errors.append(["contact", cid, str(c)[:160]])
    raw["counts"]["tagged_or_in_pipeline"] = len(contacts)

    for cid, c in contacts.items():
        lead = slim_contact(c, fids)
        lead["opps"] = opps_by_contact.get(cid, [])
        raw["leads"][cid] = lead

    # which leads need their messages: lead in on or after the day before ads went live (or every probe contact)
    picks = []
    for cid, lead in raw["leads"].items():
        t0, _ = score_mod.lead_in(lead, live)
        if probe or (t0 and t0 >= live - dt.timedelta(days=1)):
            picks.append((t0 or now, cid))
    picks.sort(reverse=True)
    if len(picks) > max_leads:
        errors.append(["bound", f"{len(picks)} leads since ads went live, read the {max_leads} newest"])
        picks = picks[:max_leads]
    raw["bounds"]["leads_read"] = len(picks)
    log(f"leads: {len(raw['leads'])} tagged or in the pipeline, {len(picks)} since ads went live")

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(read_messages, loc, cid): cid for _, cid in picks}
        for f in cf.as_completed(futs):
            cid = futs[f]
            try:
                block, errs = f.result()
            except Exception as e:  # noqa: BLE001
                block, errs = {"msgs": [], "ok": False, "truncated": False}, [["enrich", cid, str(e)[:160]]]
            raw["messages"][cid] = block
            errors += errs

    # booked leads: notes, and the length of answered calls that have none
    sales = [e for e in raw["events"] if not e["deleted"] and e["title_kind"] != "client"
             and (e["cal"] == "discovery" or e["title_kind"] == "discovery")]
    booked = [cid for cid in dict.fromkeys(e["contactId"] for e in sales) if cid in raw["messages"]]
    if len(booked) > MAX_NOTES_CONTACTS:
        errors.append(["bound", f"{len(booked)} booked leads, read notes for {MAX_NOTES_CONTACTS}"])
    jobs = []
    for cid in booked:
        for m in raw["messages"][cid]["msgs"]:
            if (m.get("type") in CALL_TYPES and str(m.get("status") or "").lower() == "completed"
                    and m.get("duration") in (None, 0)):
                jobs.append(m)
    if len(jobs) > MAX_CALL_DETAILS:
        errors.append(["bound", f"{len(jobs)} answered calls with no length, read {MAX_CALL_DETAILS}"])
        jobs = sorted(jobs, key=lambda m: str(m.get("when") or ""), reverse=True)[:MAX_CALL_DETAILS]
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        nf = {ex.submit(ghl.notes, cid): cid for cid in booked[:MAX_NOTES_CONTACTS]}
        df = {ex.submit(call_detail, loc, m): m["id"] for m in jobs}
        for f in cf.as_completed(list(nf) + list(df)):
            try:
                res = f.result()
            except Exception as e:  # noqa: BLE001
                errors.append(["detail", str(e)[:160]])
                continue
            if f in nf:
                if isinstance(res, list):
                    raw["notes"][nf[f]] = [slim_note(n) for n in res]
                else:
                    errors.append(["notes", nf[f], str(res)[:160]])
            else:
                raw["call_details"][df[f]] = res
    log(f"booked leads: {len(booked)}, call lengths read: {len(raw['call_details'])}, errors: {len(errors)}")
    return raw


def write_json(path, obj, indent=1):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only pull for Lead Suite Evidence.")
    ap.add_argument("--location", default="hq", help="config key under ghl (hq, agc, splendor)")
    ap.add_argument("--out", default=os.path.join(prof.OUT_DIR, "raw.json"))
    ap.add_argument("--max-leads", type=int, default=250)
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    p = prof.resolve(a.location)
    raw = pull(p, prof.load_settings(), max_leads=a.max_leads, workers=a.workers,
               log=lambda s: print("pull: " + s, file=sys.stderr))
    write_json(a.out, raw)
    if raw.get("fatal"):
        print("NO ACCESS: " + raw["fatal"])
        return 2
    print(f"pulled {len(raw['leads'])} leads, {len(raw['messages'])} with messages, {len(raw['events'])} calendar "
          f"events, {len(raw['errors'])} errors -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
