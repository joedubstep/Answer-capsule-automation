"""How many days of new homes the queue holds, and how many a batch adds. Read-only on carehome.db.

  python3 -m tools.lead_list.runway [--data DIR] [--batch DIR] [--pace N]

Sendable = queued homes still in queue.json whose mailbox verdict is valid or published (the engine's
due_items rule). Pace = homes that got email 1 per day over the last 7 days, unless --pace is given.
A batch's expected sendable homes = its homes with an email x the share of past addresses from the same kind of
source that came back valid (website-found addresses and state-list addresses are counted apart).
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

from . import common

SEND_OK = {"valid", "published"}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def source_kind(email_source):
    s = (email_source or "").lower()
    if "website" in s:
        return "website"
    if "state facility list" in s or "state list" in s:
        return "state list"
    return "other"


def stats(data_dir, today=None):
    today = today or dt.date.today()
    queue = {p["id"]: p for p in _load(os.path.join(data_dir, "queue.json"), [])}
    verdicts = _load(os.path.join(data_dir, "email_verify.json"), {})
    people = {p.get("id"): p for p in _load(os.path.join(data_dir, "build", "prospects.json"), [])}
    db = os.path.join(data_dir, "carehome.db")
    if not os.path.exists(db):  # the cloud-owned database was not pulled: say so instead of crashing
        return {"queued": None, "sendable_queued": None, "new_homes_last_7_days": None, "pace_per_day": None,
                "days_left": None, "valid_rate_by_source": {"website": None, "state list": None},
                "note": "no carehome.db in the data folder: run `python tools/cloud_state.py pull` first"}
    con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    try:
        queued = con.execute("SELECT id, email FROM prospects WHERE status='queued'").fetchall()
        since = (today - dt.timedelta(days=7)).isoformat()
        new7 = con.execute("SELECT COUNT(*) FROM sends WHERE step=1 AND substr(sent_at,1,10) >= ? "
                           "AND substr(sent_at,1,10) < ?", (since, today.isoformat())).fetchone()[0]
        allp = con.execute("SELECT id, email FROM prospects").fetchall()
    finally:
        con.close()
    sendable = sum(1 for pid, e in queued if pid in queue and
                   (verdicts.get((e or "").strip().lower()) or {}).get("status") in SEND_OK)
    rates = {}
    for kind in ("website", "state list"):
        n = ok = 0
        for pid, e in allp:
            v = (verdicts.get((e or "").strip().lower()) or {}).get("status")
            if v and source_kind((people.get(pid) or {}).get("email_source")) == kind:
                n += 1
                ok += v in SEND_OK
        rates[kind] = round(ok / n, 3) if n else None
    pace = round(new7 / 7.0, 1)
    return {"queued": len(queued), "sendable_queued": sendable, "new_homes_last_7_days": new7,
            "pace_per_day": pace, "days_left": round(sendable / pace, 1) if pace else None,
            "valid_rate_by_source": rates}


def batch_estimate(batch_dir, st, pace=None):
    queue = _load(os.path.join(batch_dir, "queue_additions.json"), [])
    people = {p["id"]: p for p in _load(os.path.join(batch_dir, "prospects_additions.json"), [])}
    exp = 0.0
    by_kind = {}
    for q in queue:
        kind = source_kind((people.get(q["id"]) or {}).get("email_source"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        rate = st["valid_rate_by_source"].get(kind) or st["valid_rate_by_source"].get("website") or 0.7
        exp += rate
    pace = pace or st["pace_per_day"]
    return {"homes_with_email": len(queue), "by_email_source": by_kind, "expected_sendable": round(exp),
            "pace_per_day": pace, "days_added": round(exp / pace, 1) if pace else None}


def main(argv=None):
    common.safe_stdout()
    ap = argparse.ArgumentParser(prog="lead_list.runway")
    ap.add_argument("--data", default="")
    ap.add_argument("--batch", default="")
    ap.add_argument("--pace", type=float, default=None, help="new homes a day to plan with (default: last 7 days)")
    a = ap.parse_args(argv)
    data = common.find_data_dir(a.data)
    if not data:
        print("no engine data folder found (pass --data <...>/data/carehome)")
        return 2
    st = stats(data)
    if a.pace and st["sendable_queued"] is not None:
        st["planning_pace"] = a.pace
        st["days_left_at_planning_pace"] = round(st["sendable_queued"] / a.pace, 1)
    out = {"queue": st}
    if a.batch:
        out["batch"] = batch_estimate(a.batch, st, a.pace)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
