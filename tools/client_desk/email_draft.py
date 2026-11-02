"""Monday open rooms email to referral partners, as a GoHighLevel template Joey sends himself.

It mirrors the real weekly email the home already sends ("Private and shared rooms this week"): a one-line greeting,
one line on which rooms are open, one line on the care, one line on how to reach the home for someone coming up for
discharge, and the signature. The room counts are blanks Joey fills after he hears from the owner: [N]. The first
name and the phone are GoHighLevel merge fields, so the page never shows a number. The words come from
tools/client_desk/clients.json (open_beds_email) and pass the copy checker as client text.
"""
import re

from tools.client_desk import checks
from tools.client_desk import metrics as M

BLANK = "[N]"


def _fill(s, home, city, website):
    return s.replace("{home}", home).replace("{city}", city).replace("{website}", website)


def site_label(url):
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/?#]+)", (url or "").strip())
    return m.group(1) if m else ""


def build(raw, p, recipients):
    tpl = p.get("open_beds_email")
    if not tpl:
        return {"skip": "No open rooms email for this client (no referral partner program in clients.json)."}
    if not raw.get("partner_pipeline_id"):
        return {"skip": "No referral partner pipeline found in this account, so there is nobody to send it to."}
    loc = raw.get("location") or {}
    home = loc.get("name") or p.get("label") or ""
    city = loc.get("city") or ""
    website = site_label(loc.get("website"))
    lines = [tpl["greeting"], "", _fill(tpl["rooms_line"], home, city, website), "",
             _fill(tpl["services_line"], home, city, website), "", _fill(tpl["ask_line"], home, city, website), ""]
    lines += [_fill(s, home, city, website) for s in tpl.get("signature") or []]
    body = "\n".join(lines).strip() + "\n"
    subject = tpl["subject"]
    owner_text = _fill(tpl.get("owner_text") or "", home, city, website)
    last = raw.get("open_beds_last")
    return {
        "subject": subject,
        "body": body,
        "blanks": body.count(BLANK),
        "owner_text": owner_text,
        "recipients": recipients,
        "last_sent": {"when": last["when"], "day": M.fmt_day(M.ts(last["when"])), "recipients": last["recipients"],
                      "subject": last.get("subject"), "subjects": last.get("subjects") or [last.get("subject")]}
        if last else None,
        "phone_field_ok": bool(loc.get("has_phone")),
        "check": {
            "subject": checks.check(subject, "client"),
            "body": checks.check(body, "client", template=True, blanks=(BLANK,)),
            "owner_text": checks.check(owner_text, "client") if owner_text else None,
        },
    }


def held(draft):
    if not draft or draft.get("skip"):
        return []
    return [k for k, v in (draft.get("check") or {}).items() if v and not v["ok"]]
