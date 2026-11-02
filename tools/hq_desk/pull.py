"""Read-only, bounded pull of everything the desk needs from one GoHighLevel location.

  python3 -m tools.hq_desk.pull [--location hq] [--out /tmp/hq_desk/raw.json] [--max-deals 150]

Reads: the pipelines and their stages; every deal in the location's configured pipelines (all statuses, so the
desk can tell when the last new lead came in); for each OPEN deal's contact: the contact (only the custom
fields the desk uses, never phone or email), its conversations, and the newest page of messages of its two most
recent conversations; and the sales meeting calendar from 30 days back to 14 days ahead. Never writes to GHL.
Message text is kept only for the newest few messages, trimmed, and only in /tmp (never in the repo).
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import sys

from shared import ghl, et
from tools.hq_desk import profile as prof

MSG_LIMIT = 60          # newest page of messages per conversation
CONVS_PER_CONTACT = 2
OPP_PAGES = 5           # 100 deals a page, per pipeline
WORKERS = 3             # GHL allows about 100 requests in 10 s per location, shared with the listener
KEEP_IN_BODIES = 3      # newest inbound messages that keep their text
KEEP_OUT_BODIES = 2
BODY_CHARS = 400

TYPE_BY_NUM = {1: "TYPE_CALL", 2: "TYPE_SMS", 3: "TYPE_EMAIL", 28: "TYPE_ACTIVITY_OPPORTUNITY"}


def clean_body(text, limit=BODY_CHARS):
    """Plain text from an SMS or email body: no HTML, no quoted earlier replies, trimmed."""
    if not text:
        return ""
    t = str(text)
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    lines = []
    for line in t.splitlines():
        s = line.strip()
        if re.match(r"^(on .{4,120} wrote:|-{2,}\s*original message|from:\s|sent from my )", s, re.I):
            break
        if s.startswith(">"):
            continue
        lines.append(s)
    t = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return t[:limit].rstrip() + ("..." if len(t) > limit else "")


def slim_message(m):
    meta = m.get("meta") or {}
    em = meta.get("email") or {}
    call = meta.get("call") or {}
    d = {
        "id": m.get("id"),
        "when": m.get("dateAdded"),
        "dir": m.get("direction") or em.get("direction"),
        "type": m.get("messageType") or TYPE_BY_NUM.get(m.get("type")) or "",
        "source": m.get("source"),
        "status": m.get("status") or call.get("status"),
    }
    if call.get("duration") is not None:
        d["duration"] = call.get("duration")
    if em.get("subject"):
        d["subject"] = clean_body(em.get("subject"), 120)
    return d


def slim_messages(raw_msgs):
    """Newest first. Keeps text only for the newest few inbound and outbound real messages."""
    out, n_in, n_out = [], 0, 0
    for m in raw_msgs:
        d = slim_message(m)
        real = d["type"] and not d["type"].startswith("TYPE_ACTIVITY")
        body = m.get("body")
        if real and body and d["type"] not in ("TYPE_CALL", "TYPE_CAMPAIGN_CALL"):
            if d["dir"] == "inbound" and n_in < KEEP_IN_BODIES:
                d["text"] = clean_body(body)
                n_in += 1
            elif d["dir"] == "outbound" and n_out < KEEP_OUT_BODIES:
                d["text"] = clean_body(body)
                n_out += 1
        out.append(d)
    out.sort(key=lambda x: str(x.get("when") or ""), reverse=True)
    return out


def slim_contact(c, field_ids):
    by_id = {}
    for f in c.get("customFields") or c.get("customField") or []:
        v = f.get("value", f.get("field_value"))
        if v not in (None, "", []):
            by_id[f.get("id")] = v
    fields = {role: by_id[fid] for role, fid in field_ids.items() if fid in by_id}
    return {
        "id": c.get("id"),
        "firstName": c.get("firstName") or "",
        "lastName": c.get("lastName") or "",
        "companyName": c.get("companyName") or "",
        "timezone": c.get("timezone") or "",
        "tags": [str(t) for t in (c.get("tags") or [])],
        "dnd": bool(c.get("dnd")),
        "dateAdded": c.get("dateAdded"),
        "fields": fields,
    }


def slim_opp(o, pipe_key):
    c = o.get("contact") or {}
    return {
        "id": o.get("id"),
        "name": o.get("name") or "",
        "pipeline": pipe_key,
        "pipelineId": o.get("pipelineId"),
        "stageId": o.get("pipelineStageId"),
        "status": o.get("status"),
        "contactId": o.get("contactId") or c.get("id"),
        "createdAt": o.get("createdAt"),
        "updatedAt": o.get("updatedAt"),
        "lastStageChangeAt": o.get("lastStageChangeAt"),
        "lastStatusChangeAt": o.get("lastStatusChangeAt"),
        "value": o.get("monetaryValue") or 0,
        "contactName": c.get("name") or "",
        "companyName": c.get("companyName") or "",
        "tags": [str(t) for t in (c.get("tags") or [])],
    }


def enrich_contact(loc, cid, field_ids, msg_limit=MSG_LIMIT):
    """(contact, conversation block, errors) for one contact. Never raises."""
    errors = []
    c = ghl.contact(cid)
    if ghl.ok(c) and c.get("id"):
        contact = slim_contact(c, field_ids)
    else:
        contact = None
        errors.append(["contact", cid, str(c)[:160]])
    convs = ghl.conversations(loc, contact_id=cid, limit=10)
    block = {"convs": [], "messages": [], "page_full": False}
    if not isinstance(convs, list):
        errors.append(["conversations", cid, str(convs)[:160]])
        return contact, block, errors
    convs = [x for x in convs if x.get("contactId") in (None, cid)]
    convs.sort(key=lambda x: x.get("lastMessageDate") or 0, reverse=True)
    for cv in convs[:CONVS_PER_CONTACT]:
        block["convs"].append({k: cv.get(k) for k in ("id", "type", "lastMessageDate", "lastMessageDirection",
                                                        "lastMessageType", "unreadCount")})
        r = ghl.call(f"/conversations/{cv['id']}/messages", {"limit": msg_limit}, ver=ghl.V_CONV)
        if not ghl.ok(r):
            errors.append(["messages", cv.get("id"), str(r)[:160]])
            continue
        box = r.get("messages") or {}
        batch = box.get("messages") or []
        if box.get("nextPage") or len(batch) >= msg_limit:
            block["page_full"] = True
        block["messages"] += slim_messages(batch)
    block["messages"].sort(key=lambda x: str(x.get("when") or ""), reverse=True)
    return contact, block, errors


def ms(d):
    return int(d.timestamp() * 1000)


def pull(p, now=None, max_deals=150, msg_limit=MSG_LIMIT, workers=WORKERS, log=None):
    log = log or (lambda *_: None)
    now = now or et.now_utc()
    loc = p["location"]
    raw = {"pulled_at": now.isoformat(), "location_key": p["key"], "location_id": loc,
           "deadline_et": p["deadline_et"], "skip_codes": p["skip_codes"], "joey_contact": p["joey_contact"],
           "pipelines": [], "opportunities": [], "contacts": {}, "conversations": {}, "events": [],
           "field_ids": {}, "errors": [], "bounds": {"max_deals": max_deals, "msg_limit": msg_limit}}
    errors = raw["errors"]

    if not ghl.check_access(loc):
        raw["fatal"] = "no access: this environment's GHL key does not read location " + loc
        return raw

    # stages
    pls = ghl.pipelines(loc)
    by_id = {x.get("id"): x for x in pls} if isinstance(pls, list) else {}
    if not isinstance(pls, list):
        errors.append(["pipelines", str(pls)[:160]])
    for pp in p["pipelines"]:
        x = by_id.get(pp["id"]) or {}
        raw["pipelines"].append({"key": pp["key"], "id": pp["id"], "name": x.get("name") or pp["key"],
                                 "stages": [{"id": s.get("id"), "name": s.get("name")} for s in x.get("stages") or []]})

    # contact field ids for this location
    cf_list = ghl.custom_fields(loc)
    if not isinstance(cf_list, list):
        errors.append(["customFields", str(cf_list)[:160]])
    raw["field_ids"] = prof.resolve_fields(cf_list if isinstance(cf_list, list) else None,
                                           defaults_only=not isinstance(cf_list, list))

    # deals, every status, per pipeline
    for pp in p["pipelines"]:
        r = ghl.opportunities(loc, pp["id"], status="all", max_pages=OPP_PAGES)
        if not isinstance(r, list):
            errors.append(["opportunities", pp["key"], str(r)[:160]])
            continue
        seen = set()
        for o in r:
            if o.get("pipelineId") not in (None, pp["id"]) or o.get("id") in seen:
                continue
            seen.add(o.get("id"))
            raw["opportunities"].append(slim_opp(o, pp["key"]))
    log(f"deals: {len(raw['opportunities'])}")

    # open deals -> contacts, most recently updated first, bounded
    open_opps = [o for o in raw["opportunities"] if o["status"] == "open" and o["contactId"]]
    open_opps.sort(key=lambda o: str(o.get("updatedAt") or ""), reverse=True)
    cids = []
    for o in open_opps:
        if o["contactId"] not in cids:
            cids.append(o["contactId"])
    if len(cids) > max_deals:
        errors.append(["bound", f"{len(cids)} open contacts, read the {max_deals} most recently updated"])
        cids = cids[:max_deals]
    raw["bounds"]["open_contacts"] = len(cids)

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(enrich_contact, loc, cid, raw["field_ids"], msg_limit): cid for cid in cids}
        for f in cf.as_completed(futs):
            cid = futs[f]
            try:
                contact, block, errs = f.result()
            except Exception as e:  # noqa: BLE001
                contact, block, errs = None, {"convs": [], "messages": [], "page_full": False}, [["enrich", cid, str(e)[:160]]]
            if contact:
                raw["contacts"][cid] = contact
            raw["conversations"][cid] = block
            errors += errs
    log(f"contacts: {len(raw['contacts'])}")

    # sales meetings: 30 days back, 14 ahead
    cal = p.get("meeting_calendar")
    if cal:
        evs = ghl.calendar_events(loc, cal, ms(now - dt.timedelta(days=30)), ms(now + dt.timedelta(days=14)))
        if isinstance(evs, list):
            for e in evs:
                if e.get("calendarId") not in (None, cal):
                    continue
                raw["events"].append({"id": e.get("id"), "calendarId": cal, "contactId": e.get("contactId"),
                                      "start": e.get("startTime"), "end": e.get("endTime"),
                                      "status": e.get("appointmentStatus") or e.get("status") or "",
                                      "deleted": bool(e.get("deleted")), "title": e.get("title") or ""})
        else:
            errors.append(["events", str(evs)[:160]])
    else:
        errors.append(["events", "no meeting calendar in config"])
    log(f"meetings: {len(raw['events'])}, errors: {len(errors)}")
    return raw


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only pull for the HQ desk.")
    ap.add_argument("--location", default="hq", help="config key under ghl (hq, agc, splendor)")
    ap.add_argument("--out", default=os.path.join(prof.OUT_DIR, "raw.json"))
    ap.add_argument("--max-deals", type=int, default=150)
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    p = prof.resolve(a.location)
    raw = pull(p, max_deals=a.max_deals, workers=a.workers, log=lambda s: print("pull: " + s, file=sys.stderr))
    write_json(a.out, raw)
    if raw.get("fatal"):
        print("NO ACCESS: " + raw["fatal"])
        return 2
    print(f"pulled {len(raw['opportunities'])} deals, {len(raw['contacts'])} contacts, {len(raw['events'])} meetings, "
          f"{len(raw['errors'])} errors -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
