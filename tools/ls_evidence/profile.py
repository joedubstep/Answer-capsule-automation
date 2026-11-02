"""Which GoHighLevel location the evidence reads, the ids it needs there, and the settings.

Ids come from config/surven.json (non-secret), the rules from tools/ls_evidence/settings.json. Contact fields are
found at run time from /locations/{loc}/customFields: by id when the location has that id, else by field key
(contact.stl_*), else by name. The Surven HQ ids from the build-time probe are the fallback when the list cannot be read.
"""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(REPO, "config", "surven.json")
SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
OUT_DIR = os.environ.get("LS_EVIDENCE_DIR", "/tmp/ls_evidence")
LEAD_TAG = "leadsuite"

# role -> (Surven HQ field id from the probe or None, field keys, name pattern)
FIELD_ROLES = {
    "lead_in_at": ("ntJnTEIUoaeilJ8CSGM2", ("contact.stl_lead_in_at",), r"^stl\s*lead\s*in\s*at$"),
    "first_dial_at": ("csuyMrDdyfTQjnLh6Cvp", ("contact.stl_first_dial_at",), r"^stl\s*first\s*dial\s*at$"),
    "sla_met": ("evpFk8JJJvgYX0xZToRS", ("contact.stl_sla_met",), r"^stl\s*sla\s*met$"),
    "triple_dial": ("Joxd7amkJniU3raFVIcr", ("contact.stl_triple_dial_done",), r"^stl\s*triple\s*dial"),
    "sms1": (None, ("contact.stl_sms1_in_5min", "contact.stl_sms1_done", "contact.stl_sms1"), r"^stl\s*sms\s*1(?!\d)"),
    "double_dial": ("kXDbOuYIUHJOZxhyelsJ", ("contact.stl_double_dial_after_reply",), r"^stl\s*double\s*dial"),
    "sms2": (None, ("contact.stl_sms2_done", "contact.stl_sms2"), r"^stl\s*sms\s*2(?!\d)"),
    "sms3": (None, ("contact.stl_sms3_done", "contact.stl_sms3"), r"^stl\s*sms\s*3(?!\d)"),
    "lead_replied": (None, ("contact.stl_lead_replied",), r"^stl\s*lead\s*replied"),
    "triage": ("Xt2ntxZudC5aCNLmBLvI", ("contact.stl_triage_call_done",), r"^stl\s*triage"),
    "precall_email": (None, ("contact.stl_precall_email_sent", "contact.stl_precall_video_sent"), r"^stl\s*pre-?\s*call"),
    "morning_confirm": ("eC34ROlcXVSFxqXLojEp", ("contact.stl_morning_confirm_done",), r"^stl\s*morning\s*confirm"),
    "showed": ("EXZllTjaS8yVem0Uis83", ("contact.stl_showed",), r"^stl\s*showed"),
    "noshow_count": ("7HbD1JFZPREDt5SAueOA", ("contact.stl_noshow_count", "contact.stl_no_show_count"),
                     r"^stl\s*no-?\s*show\s*count"),
    "outcome": (None, ("contact.stl_outcome",), r"^stl\s*outcome$"),
    "outcome_reason": ("uNxv8vTnlnaWxCJlGq9q", ("contact.stl_outcome_reason",), r"^stl\s*outcome\s*reason"),
    "reply_code": ("5qNYXRzPs55rPUtRwoxD", ("contact.reply_code",), r"^reply\s*code$"),
    "meeting_brief": (None, ("contact.agent_meeting_brief",), r"meeting\s*brief"),
    "test": ("ZzZnJIRyTgTBb5VYffg0", ("contact.test_contact",), r"^test\s*contact$"),
    "tz": ("5Jf00IKn2synrPTufwBB", ("contact.surven__contact_timezone",), r"contact\s*time\s*zone|contact\s*timezone"),
}
STL_BOX_ROLES = ("triple_dial", "sms1", "double_dial", "sms2", "sms3", "lead_replied", "triage", "precall_email",
                 "morning_confirm", "showed")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_settings(path=None):
    return load_json(path or SETTINGS)


def resolve(loc_key="hq", cfg=None):
    """The profile for config ghl.<loc_key>. HQ has the Leadsuite Pipeline and the two sales calendars; any other
    location (a build-time smoke test) uses its own calendars so the real API shapes still get read."""
    cfg = cfg or load_json(CONFIG)
    g = (cfg.get("ghl") or {}).get(loc_key)
    if not g or not g.get("location"):
        raise SystemExit(f"ls_evidence: no ghl.{loc_key}.location in config/surven.json")
    pipes = g.get("pipelines") or {}
    cals = g.get("calendars") or {}
    discovery = cals.get("discovery_call") or cals.get("tour")
    lead_suite = cals.get("lead_suite_personal") or (cals.get("owner_personal") if loc_key != "hq" else None)
    return {
        "key": loc_key,
        "location": g["location"],
        "pipeline": pipes.get("leadsuite"),
        "calendars": {k: v for k, v in (("discovery", discovery), ("lead_suite", lead_suite)) if v},
        "joey_contact": g.get("joey_alert_contact"),
        "artifact_url": ((cfg.get("artifacts") or {}).get("ls_evidence") or ""),
        "tag": LEAD_TAG,
    }


def resolve_fields(field_list):
    """({role: field id}, {role: how it was found}) from the location's custom field list."""
    if not isinstance(field_list, list) or not field_list:
        ids = {r: v[0] for r, v in FIELD_ROLES.items() if v[0]}
        return ids, {r: "fallback id" for r in ids}
    by_id = {f.get("id"): f for f in field_list}
    by_key = {str(f.get("fieldKey") or "").lower(): f for f in field_list}
    out, how = {}, {}
    for role, (fid, keys, pat) in FIELD_ROLES.items():
        if fid and fid in by_id:
            out[role], how[role] = fid, "id"
            continue
        hit = next((by_key[k] for k in keys if k in by_key), None)
        if hit:
            out[role], how[role] = hit.get("id"), "key"
            continue
        rx = re.compile(pat, re.I)
        hit = next((f for f in field_list if rx.search((f.get("name") or "").strip())), None)
        if hit:
            out[role], how[role] = hit.get("id"), "name"
    return out, how
