"""Monday partner call list for a client with a referral-partner pipeline.

Four groups, each oldest touch first:
  first_calls   To Call and No Answer: never reached yet.
  check_ins     Talked and Info Sent with no personal touch for 14 days or more: due the two-week check-in.
  weekly_note   Yes Partner, Info Sent and Sent a Referral (or tagged open-beds-weekly): this week's open rooms email.
  thank_yous    Sent a Referral with no personal touch since the referral: due a thank-you.

A personal touch is a call that rang, a text, a one-to-one email, or anything they sent us. The weekly open rooms
email is a bulk send, so it never counts as the check-in or the thank-you.

Joey says his own words on the phone (BUILD-SPEC rule 6), so each group carries short bullets of what to ask, never
a script. Rows show the place, the P code (Joey texts it to bridge the call), the partner type, the last touch and a
short line of what the planner knows. No phone numbers and no email addresses.
"""
import re

from tools.client_desk import metrics as M

CHECK_IN_DAYS = 14

ASK = {
    "first_calls": [
        "Ask for the person who places people: case manager, social worker, discharge planner or admissions.",
        "Get their name and the best email.",
        "Ask: can we send you the weekly open rooms email?",
        "Ask if anyone needs a place now.",
    ],
    "check_ins": [
        "Ask if the open rooms email reaches the right person.",
        "Ask if anyone is coming up for discharge soon.",
        "Ask what kind of resident they place most.",
        "If they named a person last time, ask for them by name.",
    ],
    "weekly_note": [
        "Send this week's open rooms email (below) after you fill in the rooms.",
        "A partner with no email on file needs a call first to get one.",
    ],
    "thank_yous": [
        "Thank them for the referral.",
        "Do not share how it went with the family unless the family said it is okay.",
        "Ask if anyone else is coming up.",
    ],
}

TITLES = {
    "first_calls": "Not reached yet (To Call, No Answer)",
    "check_ins": "Two-week check-in due (Talked, Info Sent)",
    "weekly_note": "On the weekly open rooms email",
    "thank_yous": "Thank-you due (Sent a Referral)",
}


def first_sentence(s, limit=150):
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    out = m.group(1) if m else s
    return out[:limit].rstrip() + ("..." if len(out) > limit else "")


def call_list(raw, cls, now):
    if not raw.get("partner_pipeline_id"):
        return None
    contacts = {c["id"]: c for c in raw.get("contacts") or []}
    msgs = M.by_contact(raw)
    names = dict(M.stage_names(raw, raw["partner_pipeline_id"]))
    groups = {k: [] for k in TITLES}
    for cid, o in M.partner_deal_by_contact(raw).items():
        if o.get("status") != "open":
            continue
        c = contacts.get(cid) or {"id": cid, "tags": []}
        stage = names.get(o.get("stageId"), "Other stage")
        st = stage.lower()
        mm = msgs.get(cid, [])
        # The weekly open rooms email is a bulk send: it is never the check-in or the thank-you, so the last touch
        # and the "due" tests use personal touches only (calls that rang, texts, one-to-one emails, their replies).
        personal = [m for m in mm if not M.open_beds_send(m)]
        t, how = M.last_touch(personal)
        if t is None:
            t_fallback = M.ts(o.get("stage_changed")) or M.ts(o.get("created"))
            days = (now - t_fallback).days if t_fallback else None
        else:
            days = (now - t).days
        out_calls = sum(1 for m in mm if M.placed(m))
        last_bulk = max((M.ts(m["when"]) for m in mm if M.open_beds_send(m) and M.sent(m) and M.ts(m.get("when"))),
                        default=None)
        since_ref = M.ts(o.get("stage_changed"))
        touched_after_ref = any(M.human_out(m) and M.ts(m.get("when")) and since_ref and M.ts(m["when"]) > since_ref
                                for m in personal)
        row = {
            "cid": cid, "label": M.label(c, "partner", o), "place": M.place(c, o), "code": M.partner_code(c),
            "type": M.partner_type(c), "stage": stage, "last_touch": t.isoformat() if t else None,
            "last_how": how or "no call, text or personal email on record", "days": days, "tries": out_calls,
            "note": first_sentence((c.get("fields") or {}).get("whisper")),
            "has_email": bool(c.get("email")), "dnd": bool(c.get("dnd")),
            "tagged_weekly": "open-beds-weekly" in (c.get("tags") or []),
            "last_open_rooms_days": (now - last_bulk).days if last_bulk else None,
        }
        if st in ("to call", "no answer"):
            groups["first_calls"].append(row)
        if st in ("talked", "info sent") and (days is None or days >= CHECK_IN_DAYS):
            groups["check_ins"].append(row)
        if st in M.PARTNER_ON_LIST or row["tagged_weekly"]:
            groups["weekly_note"].append(row)      # the email is weekly: everyone on the list gets this week's
        if st == "sent a referral" and not touched_after_ref:
            groups["thank_yous"].append(row)
    for k, rows in groups.items():
        # oldest touch first; never touched at all goes to the very top
        rows.sort(key=lambda r: (r["last_touch"] is not None, r["last_touch"] or "", r["label"]))
    return {"groups": [{"key": k, "title": TITLES[k], "ask": ASK[k], "rows": groups[k]} for k in TITLES],
            "counts": {k: len(v) for k, v in groups.items()}}


def recipients(call):
    """Who the Monday email goes to, from the weekly_note group: counts and the flags Joey should fix by hand."""
    if not call:
        return None
    rows = next((g["rows"] for g in call["groups"] if g["key"] == "weekly_note"), [])
    ok = [r for r in rows if r["has_email"] and not r["dnd"]]
    return {
        "count": len(ok),
        "labels": [r["label"] for r in ok],
        "no_email": [r["label"] for r in rows if not r["has_email"]],
        "dnd": [r["label"] for r in rows if r["dnd"]],
        "not_tagged": [r["label"] for r in ok if not r["tagged_weekly"]],
    }
