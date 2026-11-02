"""Which GoHighLevel location the desk reads, and every id it needs there.

Everything comes from config/surven.json (non-secret ids), so the same code runs on Surven HQ (the real desk)
and on American Golden Care (the build-time smoke test). Contact fields are found by their id when the
location has that id, otherwise by their name, so a location with the same planner fields under other ids
still works.
"""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(REPO, "config", "surven.json")
OUT_DIR = os.environ.get("HQ_DESK_DIR", "/tmp/hq_desk")

# role -> (Surven HQ field id, name pattern used when that id is missing in the location)
# HQ ids: follow-up-system-agent-repo tools/ghl_account.py and clients/surven-hq (memory.md, rules.md, runbook.md).
FIELD_ROLES = {
    "owed": ("AKYFgsLdEpgWkH8ATZOZ", r"promises owed"),
    "picture": ("5uekZTIesjrsq4qXmTva", r"contact picture"),
    "log": ("IMwscFpwXhfOSxY0XavX", r"plan log"),
    "next": ("SVbKsBw2h3f977KHH9mT", r"next touch"),
    "stage": ("K82Od07lPi89b2qXkDTS", r"^agent stage$"),
    "whisper": ("S3wYC4TuoY67XM3Q75MT", r"whisper"),
    "preferred": ("R1oLEswNp6xA4S9mR1gx", r"preferred name"),
    "reply_code": ("5qNYXRzPs55rPUtRwoxD", r"^reply code$"),
    "email_code": ("6pUnUwaxqRfQW3q0g2AR", r"email reply code"),
    "partner_code": (None, r"^partner code$"),
    "beds": ("Ljgi8lrRnBspiBCkUGMw", r"total beds"),
    "community": ("7qPloM1ghvJyYx5sMG2p", r"community type"),
    "tz": ("5Jf00IKn2synrPTufwBB", r"contact timezone"),
    "test": ("ZzZnJIRyTgTBb5VYffg0", r"^test contact$"),
    "suppressed": ("S8XwLPke4oVq9cywNpuL", r"global suppressed"),
    "callback_at": ("wdAcNLAluJsrEew8OzRW", r"agent callback at"),
    "noshow_count": ("7HbD1JFZPREDt5SAueOA", r"no-show count"),
    "home": (None, r"facility name|community name|home name|business name"),
}

# Which calendar counts as "the sales meeting" in each location (first key found wins).
MEETING_CALENDAR_KEYS = ("discovery_call", "tour")
# Pipelines walked in this order (closest to money first when a contact has deals in two).
PIPELINE_ORDER = ("email", "leadsuite", "warm_referral", "normal_lead", "family_journey", "referral_partners")


def load_config(path=None):
    with open(path or CONFIG, encoding="utf-8") as f:
        return json.load(f)


def resolve(loc_key="hq", cfg=None):
    """The profile for a location key in config ghl.<key> (hq, agc, splendor)."""
    cfg = cfg or load_config()
    g = (cfg.get("ghl") or {}).get(loc_key)
    if not g or not g.get("location"):
        raise SystemExit(f"hq_desk: no ghl.{loc_key}.location in config/surven.json")
    pipes = g.get("pipelines") or {}
    order = [k for k in PIPELINE_ORDER if k in pipes] + [k for k in pipes if k not in PIPELINE_ORDER]
    cals = g.get("calendars") or {}
    meeting_cal = next((cals[k] for k in MEETING_CALENDAR_KEYS if cals.get(k)), None)
    if not meeting_cal and cals:
        meeting_cal = next(iter(cals.values()))
    desk = cfg.get("hq_desk") or {}
    return {
        "key": loc_key,
        "location": g["location"],
        "pipelines": [{"key": k, "id": pipes[k]} for k in order],
        "meeting_calendar": meeting_cal,
        "joey_contact": g.get("joey_alert_contact"),
        "deadline_et": ((cfg.get("campaign") or {}).get("price_raise_deadline_et") or ""),
        "artifact_url": ((cfg.get("artifacts") or {}).get("hq_desk") or ""),
        # optional, filled at deploy: lead codes Joey said never to work (codes only, never names)
        "skip_codes": [str(c) for c in (desk.get("skip_codes") or [])],
        "default_field_ids": {r: v[0] for r, v in FIELD_ROLES.items() if v[0]},
    }


def resolve_fields(field_list, defaults_only=False):
    """{role: field id} from the location's custom field list [{id, name}]. Missing roles are left out."""
    if defaults_only or not isinstance(field_list, list) or not field_list:
        return {r: v[0] for r, v in FIELD_ROLES.items() if v[0]}
    ids = {f.get("id") for f in field_list}
    out = {}
    for role, (fid, pat) in FIELD_ROLES.items():
        if fid and fid in ids:
            out[role] = fid
            continue
        rx = re.compile(pat, re.I)
        for f in field_list:
            if rx.search((f.get("name") or "").strip()):
                out[role] = f.get("id")
                break
    return out
