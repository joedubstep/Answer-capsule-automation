"""Load one client's settings: tools/client_desk/clients.json merged with config/surven.json.

  from tools.client_desk import profile
  p = profile.load("agc")      # dict, see keys below

Keys: key, label, short, location, env, env_id, since, family_pipeline, partner_pipeline, tour_calendar,
internal_contacts (config ids + Joey's alert contact), test_events, fields (role -> default field id),
field_names (role -> names to look for), goal, partner_goal, operator_voice_names, open_beds_email,
artifact_key, artifact_url (the desk page), report_artifact_key, report_artifact_url (the owner report page; config key
artifacts.client_desk_<client>_report), internal_domains, out_dir.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CONFIG = os.path.join(ROOT, "config", "surven.json")
CLIENTS = os.path.join(HERE, "clients.json")
OUT_ROOT = os.environ.get("CLIENT_DESK_DIR", "/tmp/client_desk")

# Field roles the desk reads, and the GoHighLevel field names to find them by (first match wins).
FIELD_NAMES = {
    "agent_stage": ["Agent Stage"],
    "call_outcome": ["SVN Call Outcome"],
    "tour_result": ["SVN Tour Result", "SVN Tour Result (owner fills)"],
    "partner_code": ["Partner Code"],
    "referred_by": ["Referred By Partner"],
    "whisper": ["Agent Whisper"],
    "last_transcript": ["SVN Last Call Transcript"],
    "move_in_date": ["Move-In Date"],
    "reply_code": ["Reply Code"],
}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def keys():
    return [k for k in _read(CLIENTS) if not k.startswith("_")]


def load(key, config_path=None, clients_path=None):
    clients = _read(clients_path or CLIENTS)
    if key not in clients or key.startswith("_"):
        raise KeyError("unknown client %r (known: %s)" % (key, ", ".join(keys())))
    c = clients[key]
    sv = _read(config_path or CONFIG)
    g = (sv.get("ghl") or {}).get(c.get("ghl_key") or key) or {}
    fields = {}
    if c.get("ghl_key") == "agc":  # AGC field ids known in config/surven.json
        f = g.get("fields") or {}
        fields.update({"agent_stage": f.get("agent_stage"), "call_outcome": f.get("svn_call_outcome"),
                       "tour_result": f.get("svn_tour_result")})
    fields.update(c.get("fields") or {})
    internal = list(c.get("internal_contacts") or [])
    if g.get("joey_alert_contact") and g["joey_alert_contact"] not in internal:
        internal.append(g["joey_alert_contact"])
    domains = {"surven.ai"} | {d.lower() for d in sv.get("cold_email_domains") or []}
    fam, par, cal = (dict(c.get(k) or {}) for k in ("family_pipeline", "partner_pipeline", "tour_calendar"))
    pipes = g.get("pipelines") or {}
    if not fam.get("id") and pipes.get("family_journey"):
        fam["id"] = pipes["family_journey"]
    if not par.get("id") and pipes.get("referral_partners"):
        par["id"] = pipes["referral_partners"]
    if not cal.get("id") and (g.get("calendars") or {}).get("tour"):
        cal["id"] = g["calendars"]["tour"]
    return {
        "key": key,
        "label": c.get("label") or key,
        "short": c.get("short") or key.upper(),
        "location": c.get("location") or g.get("location"),
        "env": c.get("env"),
        "env_id": (sv.get("envs") or {}).get(c.get("env") or ""),
        "since": c.get("since") or "2026-01-01",
        "family_pipeline": fam,
        "partner_pipeline": par,
        "tour_calendar": cal,
        "internal_contacts": internal,
        "test_events": list(c.get("test_events") or []),
        "fields": {k: v for k, v in fields.items() if v},
        "field_names": FIELD_NAMES,
        "goal": c.get("goal") or {},
        "partner_goal": c.get("partner_goal"),
        "operator_voice_names": [n.lower() for n in c.get("operator_voice_names") or ["joey"]],
        "open_beds_email": c.get("open_beds_email"),
        "artifact_key": c.get("artifact_key") or "client_desk_" + key,
        "artifact_url": (sv.get("artifacts") or {}).get(c.get("artifact_key") or "client_desk_" + key) or "",
        # the owner report is its own private page (published from /tmp with file_path, like every desk page)
        "report_artifact_key": (c.get("artifact_key") or "client_desk_" + key) + "_report",
        "report_artifact_url": (sv.get("artifacts") or {}).get((c.get("artifact_key") or "client_desk_" + key)
                                                               + "_report") or "",
        "internal_domains": sorted(domains),
        "out_dir": os.path.join(OUT_ROOT, key),
    }
