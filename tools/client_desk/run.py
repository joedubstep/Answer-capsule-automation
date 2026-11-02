"""Run the Client Desk for one client, end to end or one half at a time.

  python3 -m tools.client_desk.run --client agc --mode monday            pull + build + render (Monday run)
  python3 -m tools.client_desk.run --client agc --mode friday --dry-run  same, Friday run, marked as a dry run
  python3 -m tools.client_desk.run --client agc --mode auto              Monday on Mondays, Friday on Fridays, else full
  python3 -m tools.client_desk.run --client agc --stage data             pull + numbers only, writes brief.json
  python3 -m tools.client_desk.run --client agc --stage page [--notes notes.json]   apply notes, check, render

Modes: monday (partner call list, open rooms email, caller triage), friday (owner report, caller triage), full
(everything; on-demand runs on other days). The script itself never publishes, texts or writes to GoHighLevel.
Files land in /tmp/client_desk/<client>/ (or --out-dir): raw.json, view.json, brief.json, client_desk.html (the ops
page, published to artifacts.client_desk_<client>), report.html (the owner report page, published as its own page to
artifacts.client_desk_<client>_report), report.txt, email.txt, push.txt (one line for the push notification).
Exit 0 ok, 1 something client-facing is held by the copy checker, 2 cannot read GoHighLevel.
"""
import argparse
import json
import os
import sys

from shared import et
from tools.client_desk import profile as prof
from tools.client_desk import pull as pull_mod
from tools.client_desk import metrics as M
from tools.client_desk import triage as T
from tools.client_desk import partners as P
from tools.client_desk import email_draft as EM
from tools.client_desk import report as R
from tools.client_desk import render as RD
from tools.client_desk import checks as C

VERDICTS = ("robocall-likely", "family-likely", "not-a-family", "unclear")


def files(out_dir):
    return {k: os.path.join(out_dir, v) for k, v in {
        "raw": "raw.json", "view": "view.json", "brief": "brief.json", "notes": "notes.json",
        "page": "client_desk.html", "report": "report.html", "report_txt": "report.txt", "email_txt": "email.txt",
        "push": "push.txt"}.items()}


def resolve_mode(mode, now):
    if mode != "auto":
        return mode
    wd = et.to_et(now).weekday()
    return {0: "monday", 4: "friday"}.get(wd, "full")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_view(raw, p, now, mode, dry_run=False):
    desk, cls = M.build(raw, p, now, mode)
    items = T.triage(raw, cls, p, now)
    call = P.call_list(raw, cls, now)
    view = {"client": p["key"], "mode": mode, "dry_run": dry_run, "desk": desk, "triage": items,
            "triage_counts": T.counts(items), "call": call, "email": None, "report": None,
            "report_url": p.get("report_artifact_url") or ""}
    rc = P.recipients(call)
    counts = dict((call or {}).get("counts") or {})
    if rc is not None:
        counts["email_recipients"] = rc["count"]
    view["report_counts"] = counts
    if mode in ("monday", "full"):
        view["email"] = EM.build(raw, p, rc)
    if mode in ("friday", "full"):
        view["report"] = R.build(desk, counts, triage_items=items)
    return view


def brief(view):
    """What the model reads: the counts, the callers it may re-judge, and the report text. Small on purpose."""
    d = view["desk"]
    return {
        "client": view["client"], "mode": view["mode"], "top_line": RD.top_line(view),
        "families": d["families"], "tours": d["tours"], "move_ins": d["move_ins"], "goal": d["goal"],
        "partners": {k: v for k, v in (d.get("partners") or {}).items() if k in ("total", "on_weekly_list", "sent_referral", "moves", "touches")} or None,
        "activity": d["activity"], "unanswered": len(d.get("unanswered") or []),
        "callers": [{"id": i["cid"], "label": i["label"], "verdict": i["verdict"], "lean": i["lean"], "reason": i["reason"],
                     "heard": [c["heard"] for c in i["calls"] if c.get("heard")][-3:],
                     "texts": [t["text"] for t in i.get("texts") or []]}
                    for i in view["triage"] if i["verdict"] in ("unclear", "family-likely", "not-a-family")],
        "report_text": (view.get("report") or {}).get("text"),
        "held": held(view),
        "errors": d.get("errors"),
    }


def held(view):
    out = []
    rep = view.get("report")
    if rep:
        out += ["report " + k for k, v in rep["check"].items() if v and not v["ok"]]
    out += ["email " + k for k in EM.held(view.get("email"))]
    return out


def apply_notes(view, notes):
    """The model's optional judgment: a short note for the owner report, and re-judged unknown callers."""
    lines = []
    over = (notes or {}).get("triage") or {}
    for i in view["triage"]:
        o = over.get(i["cid"])
        if not isinstance(o, dict) or o.get("verdict") not in VERDICTS:
            continue
        i["verdict"], i["lean"] = o["verdict"], ""
        i["reason"] = (str(o.get("reason") or i["reason"])[:220] + " (checked by Claude)").strip()
        ans = {"robocall-likely": "robocall", "family-likely": "family", "not-a-family": "not a family",
               "unclear": "not sure yet"}[i["verdict"]]
        i["answer"] = "%s: %s" % (i["label"], ans)
        lines.append("triage override: %s -> %s" % (i["label"], i["verdict"]))
    view["triage_counts"] = T.counts(view["triage"])
    note = str((notes or {}).get("report_note") or "").strip()
    if note and view.get("report") is not None:
        res = C.check(note, "client")
        if res["ok"]:
            view["report"] = R.build(view["desk"], view.get("report_counts") or {}, note=note[:400],
                                     triage_items=view["triage"])
            lines.append("report note added")
        else:
            lines.append("report note HELD, left out: " + C.summary(res))
    return lines


def stage_data(p, F, now, mode, dry_run, days):
    for k in ("notes", "push", "page", "report", "report_txt", "email_txt"):
        if os.path.exists(F[k]):
            os.remove(F[k])          # never carry last run's notes or pages into this one
    raw = pull_mod.pull(p, now=now, days=days, log=lambda s: print("pull: " + s, file=sys.stderr))
    pull_mod.write_json(F["raw"], raw)
    if raw.get("fatal"):
        print("NO ACCESS: " + raw["fatal"])
        return 2, None
    view = build_view(raw, p, now, mode, dry_run)
    pull_mod.write_json(F["view"], view)
    pull_mod.write_json(F["brief"], brief(view))
    d = view["desk"]
    f, t, mi, g = d["families"], d["tours"], d["move_ins"], d["goal"]
    print("data: %d contacts (%s), %d deals, %d messages in %d days, %d read errors" % (
        len(raw["contacts"]), ", ".join("%s %d" % kv for kv in sorted(d["kinds"].items())),
        len(raw["opportunities"]), len(raw["messages"]), raw["days"], len(raw["errors"])))
    print("messages from: %s (%s conversations read)" % (raw.get("message_source"), raw.get("conversations_read")))
    print("families: %d total, %d new in 7 days, %d talked with in 7 days; half reached within %s (7 days, n=%d), "
          "%s (30 days, n=%d)" % (f["total"], f["new_week"], f["reached_week"], f["speed_week_min"], f["speed_week_n"],
                                  f["speed_month_min"], f["speed_month_n"]))
    print("tours: %d booked and %d held in 7 days, %d upcoming, %d families toured so far (%d calendar, %d stage only); "
          "move-ins %d%s" % (t["booked_week"], t["held_week"], t["upcoming"], t["toured_to_date"], t["toured_calendar"],
                             t["toured_stage_only"], mi["to_date"], (" of %d" % g["move_ins"]) if g.get("move_ins") else ""))
    pa = d.get("partners")
    if pa:
        print("partners: %d deals: %s; moved in 7 days %d; last move %s; touches %d to %d partners" % (
            pa["total"], ", ".join("%s %d" % (r["name"], r["total"]) for r in pa["stages"]), pa["moves"]["moved"],
            (pa["moves"]["last_move"] or "none")[:10], pa["touches"]["touches"], pa["touches"]["partners_touched"]))
    a = d["activity"]
    print("activity 7 days: %d calls (%d by hand), %d texts (%d by hand), %d emails, %d calls answered" % (
        a["calls"], a["calls_by_hand"], a["texts"], a["texts_by_hand"], a["emails"], a["calls_answered"]))
    print("triage: %d callers: %s" % (len(view["triage"]), ", ".join("%d %s" % (v, k) for k, v in view["triage_counts"].items())))
    print("unanswered over 24h: %d" % len(d["unanswered"]))
    return 0, view


def stage_page(p, F, notes_path, dry_run):
    view = load(F["view"])
    view["dry_run"] = dry_run or view.get("dry_run", False)
    notes = load(notes_path) if notes_path and os.path.exists(notes_path) else None
    for line in apply_notes(view, notes):
        print(line)
    pull_mod.write_json(F["view"], view)
    if view.get("email") and not view["email"].get("skip"):
        em = view["email"]
        with open(F["email_txt"], "w", encoding="utf-8") as f:
            f.write("Subject: %s\n\n%s" % (em["subject"], em["body"]))
        print("email: %s; %d blanks to fill; due for %d partners; %s" % (
            "HELD" if EM.held(em) else "ready", em["blanks"], (em.get("recipients") or {}).get("count", 0),
            C.summary(em["check"]["body"])))
    elif view.get("email"):
        print("email: skipped: " + view["email"]["skip"])
    if view.get("report"):
        rep = view["report"]
        with open(F["report"], "w", encoding="utf-8") as f:
            f.write(RD.render_report(rep, view["desk"]["short"]))
        with open(F["report_txt"], "w", encoding="utf-8") as f:
            f.write(rep["text"] + "\n")
        ok = rep["check"]["page"]["ok"] and rep["check"]["text"]["ok"]
        print("report: %s -> %s; %s" % ("ready" if ok else "HELD", F["report"], C.summary(rep["check"]["page"])))
    page = RD.render_page(view)
    with open(F["page"], "w", encoding="utf-8") as f:
        f.write(page)
    top = RD.top_line(view)
    with open(F["push"], "w", encoding="utf-8") as f:
        f.write(top[:230] + "\n")
    print("page: %s (%d bytes)" % (F["page"], len(page)))
    print(("WOULD PUSH: " if dry_run else "PUSH: ") + top[:230])
    if dry_run:
        print("DRY RUN: nothing published, nothing pushed, nothing sent.")
    h = held(view)
    for x in h:
        print("HELD " + x)
    return 1 if h else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Client Desk runner (read-only).")
    ap.add_argument("--client", required=True, help="agc or splendor (tools/client_desk/clients.json)")
    ap.add_argument("--mode", choices=["monday", "friday", "full", "auto"], default="auto")
    ap.add_argument("--stage", choices=["all", "data", "page"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--notes", help="optional notes.json from the model (report note, caller re-judgments)")
    ap.add_argument("--days", type=int, default=pull_mod.LOOKBACK_DAYS)
    ap.add_argument("--now", help="ISO time (tests)")
    ap.add_argument("--out-dir")
    a = ap.parse_args(argv)
    p = prof.load(a.client)
    out = a.out_dir or p["out_dir"]
    os.makedirs(out, exist_ok=True)
    F = files(out)
    now = et.parse(a.now) if a.now else et.now_utc()
    mode = resolve_mode(a.mode, now)
    code = 0
    if a.stage in ("all", "data"):
        code, _ = stage_data(p, F, now, mode, a.dry_run, a.days)
        if code:
            return code
    if a.stage in ("all", "page"):
        if not os.path.exists(F["view"]):
            print("no view.json yet: run --stage data first")
            return 2
        code = stage_page(p, F, a.notes or F["notes"], a.dry_run)
    return code


if __name__ == "__main__":
    sys.exit(main())
