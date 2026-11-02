"""Surven HQ GoHighLevel phone calls for one log day, read-only (Surven HQ environment only).

  python3 -m tools.time_ledger.ghl_calls --day 2026-11-01 [--out /tmp/time_ledger/ghl_calls.json]

Used two ways: as evidence for blank blocks ("made 12 calls, 2 answered") and for the daily line (dials and
talk minutes next to the logged call time). Keeps only the time, talk minutes, direction and whether it was
answered: no phone numbers, no names, no contact ids. In any other environment it writes {"unavailable": ...}.
"""
import argparse
import datetime as dt
import sys

from shared import ghl, et
from tools.time_ledger import common as C

HQ_LOCATION = "EeadFhXhDOJ1DWE4ArhK"
CALL_TYPES = {"TYPE_CALL", "TYPE_CAMPAIGN_CALL", "TYPE_IVR_CALL"}
MAX_PAGES = 30


def _iso_z(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def day_window(day):
    """Work day: 4am ET on `day` to 4am ET the next day, as aware UTC datetimes."""
    start = et.et_to_utc(dt.datetime.combine(day, dt.time(4, 0)))
    end = et.et_to_utc(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(4, 0)))
    return start, end


def _export(location, start, end):
    params = {"locationId": location, "limit": 100, "startDate": _iso_z(start), "endDate": _iso_z(end)}
    got, err = {}, None
    for _ in range(MAX_PAGES):
        r = ghl.call("/conversations/messages/export", params, ver=ghl.V_CONV)
        if not ghl.ok(r):
            err = r
            break
        batch = r.get("messages") or []
        for m in batch:
            if m.get("id"):
                got[m["id"]] = m
        cur = r.get("nextCursor")
        if not cur or not batch:
            break
        params["cursor"] = cur
    return list(got.values()), err


def slim(m, day):
    typ = m.get("messageType") or {1: "TYPE_CALL"}.get(m.get("type"), "")
    if typ not in CALL_TYPES:
        return None
    when = et.parse(m.get("dateAdded"))
    if not when:
        return None
    local = et.to_et(when)
    mins = (local.date() - day).days * 1440 + local.hour * 60 + local.minute
    call = (m.get("meta") or {}).get("call") or {}
    dur = call.get("duration")
    talk = round(float(dur) / 60.0, 1) if isinstance(dur, (int, float)) else 0.0
    status = str(call.get("status") or m.get("status") or "").lower()
    return {"t": mins, "clock": C.fmt_clock(mins), "min": talk,
            "dir": str(m.get("direction") or "").lower() or "outbound",
            "answered": status == "completed" and talk >= 0.5}


def pull(day, location=HQ_LOCATION):
    if not ghl.check_access(location):
        return {"day": day.isoformat(), "calls": [],
                "unavailable": "this environment cannot read Surven HQ GoHighLevel (run it in the Surven HQ env)"}
    start, end = day_window(day)
    union, err = {}, None
    for _ in range(2):                      # the export sometimes comes back short; a second pass fills gaps
        got, e = _export(location, start, end)
        err = err or e
        before = len(union)
        for m in got:
            union[m["id"]] = m
        if len(union) == before:
            break
    calls = [c for c in (slim(m, day) for m in union.values()) if c]
    calls.sort(key=lambda c: c["t"])
    out = {"day": day.isoformat(), "calls": calls}
    if err and not calls:
        out["unavailable"] = "GoHighLevel export failed (%s)" % err.get("error")
    return out


def summary(data, start=None, end=None):
    """Dials, answered and talk minutes, optionally inside [start, end) minutes."""
    cs = [c for c in data.get("calls", []) if c["dir"] == "outbound" and
          (start is None or c["t"] >= start) and (end is None or c["t"] < end)]
    return {"dials": len(cs), "answered": sum(1 for c in cs if c["answered"]),
            "talk_min": round(sum(c["min"] for c in cs), 1),
            "first": cs[0]["t"] if cs else None, "last": cs[-1]["t"] if cs else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--day", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    day = C.parse_day(a.day)
    data = pull(day)
    out = a.out or C.wpath("ghl_calls_%s.json" % day.isoformat())
    C.write_json(out, data)
    if data.get("unavailable"):
        print("GHL CALLS UNAVAILABLE: " + data["unavailable"])
        return 0
    s = summary(data)
    print("GHL calls %s: %d outbound dials, %d answered, %s talk min -> %s" % (
        day.isoformat(), s["dials"], s["answered"], s["talk_min"], out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
