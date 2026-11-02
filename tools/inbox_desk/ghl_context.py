"""Lead context from Surven HQ GoHighLevel for cold email replies. READ-ONLY.

  python3 -m tools.inbox_desk.ghl_context [--work /tmp/inbox_desk/work.json]

For each cold reply in work.json it finds the HQ contact by the sender's email and adds, under item["ghl"]:
  code (E24), stage (Email Pipeline stage name), deal status, talked (a call of 60s+ on record),
  answered (an outbound email, text or call in GoHighLevel after the reply), contact id.
It also writes item["cleanup"] for opt-outs that still have an E code or an open deal, so the digest can tell
Joey to close them by hand. Nothing is ever written to GoHighLevel.

Works only where the environment's key reads the Surven HQ location (the Surven HQ cloud environment). Anywhere
else it prints "GHL: no access to Surven HQ here, skipped" and leaves work.json as it was (exit 0).
Tests: GHL_FAKE_DIR (see shared/ghl.py).
"""
import argparse
import json
import os
import sys

from shared import et, ghl
from tools.inbox_desk import settings as st

CALL_TYPES = ("TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_IVR_CALL")
OUT_TYPES = ("TYPE_EMAIL", "TYPE_SMS", "TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_CUSTOM_EMAIL", "TYPE_CUSTOM_SMS")


def hq(cfg=None):
    cfg = cfg or st._load(st.CONFIG, {})
    h = (cfg.get("ghl") or {}).get("hq") or {}
    return {"location": h.get("location"), "code_field": h.get("code_field_email_reply"),
            "email_pipeline": (h.get("pipelines") or {}).get("email")}


def find_contact(loc, email):
    r = ghl.call("/contacts/", {"locationId": loc, "query": email, "limit": 5})
    if not ghl.ok(r):
        return None
    for c in r.get("contacts") or []:
        if (c.get("email") or "").strip().lower() == email.lower():
            return c
    return None


def stage_names(loc):
    out = {}
    pipes = ghl.pipelines(loc)
    for p in pipes if isinstance(pipes, list) else []:
        for s in p.get("stages") or []:
            out[s.get("id")] = s.get("name")
    return out


def _duration(m):
    meta = m.get("meta") or {}
    call = meta.get("call") or {}
    for v in (call.get("duration"), meta.get("duration"), m.get("duration")):
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return 0


def lead_context(loc, item, code_field, stages, email_pipeline=None):
    c = find_contact(loc, item.get("from") or "")
    if not c:
        return {"found": False}
    full = ghl.contact(c["id"])
    full = full if isinstance(full, dict) and "error" not in full else c
    code = ghl.custom_value(full, code_field) if code_field else ""
    out = {"found": True, "contact_id": c["id"], "code": ("E" + str(code).lstrip("Ee")) if str(code).strip() else "",
           "tags": [str(t) for t in (full.get("tags") or [])], "dnd": bool(full.get("dnd"))}
    r = ghl.call("/opportunities/search", {"location_id": loc, "contact_id": c["id"], "limit": 20})
    opps = [o for o in (r.get("opportunities") or []) if o.get("contactId") in (None, c["id"])] if ghl.ok(r) else []
    if email_pipeline:
        opps = [o for o in opps if o.get("pipelineId") in (None, email_pipeline)] or opps
    if opps:
        o = sorted(opps, key=lambda x: x.get("updatedAt") or "", reverse=True)[0]
        out["stage"] = stages.get(o.get("pipelineStageId"), "")
        out["deal_status"] = o.get("status") or ""
    replied_at = et.parse(item.get("date_utc") or "") or et.parse(item.get("date") or "")
    talked, answered = False, False
    convs = ghl.conversations(loc, contact_id=c["id"], limit=5)
    mine = [cv for cv in (convs if isinstance(convs, list) else []) if cv.get("contactId") in (None, c["id"])]
    for cv in mine[:2]:  # newest two conversations, one page of messages each: bounded cost
        msgs = ghl.messages(cv["id"], max_pages=1)
        for m in msgs if isinstance(msgs, list) else []:
            t = m.get("messageType") or m.get("type") or ""
            if t in CALL_TYPES and _duration(m) >= 60:
                talked = True
            when = et.parse(m.get("dateAdded"))
            # a call counts as an answer only when they talked (60s+); a missed dial is not an answer to the email
            reached = t not in CALL_TYPES or _duration(m) >= 60
            if m.get("direction") == "outbound" and t in OUT_TYPES and reached and replied_at and when \
                    and when > replied_at:
                answered = True
    out["talked"], out["answered"] = talked, answered
    return out


def cleanup_line(item, g):
    """A one-line GHL cleanup task for an opt-out that still looks live in GHL, else ''."""
    if item.get("sub") != "opt_out" or not g.get("found"):
        return ""
    live = g.get("code") or (g.get("deal_status") == "open")
    if not live:
        return ""
    who = g.get("code") or (item.get("home") or item.get("from_domain") or "a home")
    bits = []
    if g.get("code"):
        bits.append("still has code " + g["code"])
    if g.get("deal_status") == "open":
        bits.append("an open deal" + (" at " + g["stage"] if g.get("stage") else ""))
    return f"{who} opted out but {' and '.join(bits)} in GHL. Mark the deal lost and keep them out of follow-ups."


def enrich(items, cfg=None, log=print):
    h = hq(cfg)
    if not h["location"] or not ghl.check_access(h["location"]):
        log("GHL: no access to Surven HQ here, skipped")
        return items, False
    stages = stage_names(h["location"])
    n = 0
    for it in items:
        if it.get("class") != "cold_reply" or not it.get("from"):
            continue
        g = lead_context(h["location"], it, h["code_field"], stages, h["email_pipeline"])
        it["ghl"] = g
        n += 1
        line = cleanup_line(it, g)
        if line:
            it["cleanup"] = line
            it["needs_joey"] = True
        if g.get("answered") and it.get("action") in ("draft_reply", "draft_plan"):
            it["reasons"] = list(it.get("reasons") or []) + ["already answered in GoHighLevel"]
            it["action"], it["needs_joey"] = "label_only", False
    log(f"GHL: looked up {n} cold repl{'y' if n == 1 else 'ies'} in Surven HQ (read-only)")
    return items, True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add read-only HQ GoHighLevel context to cold replies.")
    ap.add_argument("--work", default=os.path.join(st.OUT_DIR, "work.json"))
    a = ap.parse_args(argv)
    try:
        with open(a.work, encoding="utf-8") as f:
            work = json.load(f)
    except (OSError, ValueError):
        print("GHL: no work.json, run desk classify first")
        return 2
    items = work["items"] if isinstance(work, dict) else work
    items, used = enrich(items)
    if used:
        if isinstance(work, dict):
            work["items"], work["ghl"] = items, True
        with open(a.work, "w", encoding="utf-8") as f:
            json.dump(work, f, indent=1)
        for it in items:
            g = it.get("ghl") or {}
            if g:
                print(f"  {it['thread_id']}  {g.get('code') or 'no code'}  {g.get('stage') or ''}  "
                      f"{'talked' if g.get('talked') else ''} {'answered' if g.get('answered') else ''}"
                      + ("  CLEANUP" if it.get("cleanup") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
