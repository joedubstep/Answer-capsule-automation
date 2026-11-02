"""Run Lead Suite Evidence end to end: pull, score, render. It never publishes and never texts.

  python3 -m tools.ls_evidence.run --location hq [--prev <last page>] [--entered-through 2026-11-01]
  python3 -m tools.ls_evidence.run --location agc --dry-run [--probe 25]     build-time smoke test on other data

Files (in /tmp/ls_evidence unless LS_EVIDENCE_DIR is set): raw.json, evidence.json, ls_evidence.html.
--probe N (never on hq) also scores the N newest contacts of a test location as if they were leads, so the real
message shapes get exercised. Exit 0 ok, 2 cannot read GHL.
"""
import argparse
import datetime as dt
import os
import sys

from shared import et
from tools.ls_evidence import profile as prof
from tools.ls_evidence import pull as pull_mod
from tools.ls_evidence import score as score_mod
from tools.ls_evidence import render as render_mod


def paths(out_dir):
    return {k: os.path.join(out_dir, v) for k, v in {
        "raw": "raw.json", "evidence": "evidence.json", "page": "ls_evidence.html"}.items()}


def summary(ev):
    b, w, s, p = ev["scoreboard"], ev["window"], ev["sop"], ev["portal"]
    pct = (lambda x: "none due" if x["pct"] is None else f"{x['pct']}%")
    lines = [
        f"scoreboard: {b['qualified_booked']} of {b['target']} qualified calls booked ({b['booked_in_window']} booked "
        f"in the window, {b['unqualified']} not qualified, {b['cancelled']} cancelled), {b['held']} showed; "
        f"window {w['live']} to {w['end']}, {w['used']} days used, {max(0, w['left'])} left",
        f"sop: leads {pct(s['leads'])} ({s['leads']['yes']} yes, {s['leads']['no']} no), calls {pct(s['calls'])} "
        f"({s['calls']['yes']} yes, {s['calls']['no']} no); {b['leads']} leads since ads went live",
        f"portal: {len(p['new_leads'])} new lead rows, {len(p['changed_leads'])} changed; {len(p['new_calls'])} new call "
        f"rows, {len(p['changed_calls'])} changed; waiting {len(p['waiting_leads'])} leads, {len(p['waiting_calls'])} "
        f"calls" + (" (first run: everything finished is listed)" if p["first_run"] else ""),
        "stands: " + b["line"],
    ]
    fr = ev["field_report"]
    lines.append(f"fields: STL fields found {len(fr['found'])}, missing {', '.join(fr['missing']) or 'none'}; "
                 f"{fr['leads_with_any']} of {fr['leads']} leads have any box field filled")
    errs = [e for e in ev.get("errors") or [] if e and e[0] != "bound"]
    bound = [e[1] for e in ev.get("errors") or [] if e and e[0] == "bound"]
    lines.append(f"errors: {len(errs)} read errors" + (f"; bounds hit: {'; '.join(bound)}" if bound else ""))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lead Suite Evidence runner.")
    ap.add_argument("--location", default="hq")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prev", help="the page as last published (from the Artifact read)")
    ap.add_argument("--entered-through", help="Eastern date: rows on or before it are already in the portal")
    ap.add_argument("--settings", default=prof.SETTINGS)
    ap.add_argument("--max-leads", type=int, default=250)
    ap.add_argument("--workers", type=int, default=pull_mod.WORKERS)
    ap.add_argument("--probe", type=int, default=0, help="test locations only: also score the N newest contacts")
    ap.add_argument("--now", help="ISO time (tests)")
    ap.add_argument("--out-dir", default=prof.OUT_DIR)
    a = ap.parse_args(argv)
    if a.probe and a.location == "hq":
        print("--probe is for test locations only, never hq")
        return 2
    if a.entered_through:
        try:
            dt.date.fromisoformat(a.entered_through)
        except ValueError:
            print("--entered-through must be a date like 2026-11-01")
            return 2
    p = prof.resolve(a.location)
    settings = prof.load_settings(a.settings)
    P = paths(a.out_dir)
    os.makedirs(a.out_dir, exist_ok=True)
    if os.path.exists(P["page"]):
        os.remove(P["page"])               # never publish last run's page by mistake
    now = et.parse(a.now) if a.now else et.now_utc()
    raw = pull_mod.pull(p, settings, now=now, max_leads=a.max_leads, workers=a.workers, probe=a.probe,
                        log=lambda s: print("pull: " + s, file=sys.stderr))
    pull_mod.write_json(P["raw"], raw)
    if raw.get("fatal"):
        print("NO ACCESS: " + raw["fatal"])
        return 2
    prev = score_mod.read_prev_state(a.prev)
    if a.prev and prev is None:
        print(f"prev: no state found in {a.prev}, so every finished row counts as new")
    ev = score_mod.build(raw, settings, now=now, prev=prev, entered_through=a.entered_through)
    pull_mod.write_json(P["evidence"], ev)
    page = render_mod.render(ev)
    with open(P["page"], "w", encoding="utf-8") as f:
        f.write(page)
    for line in summary(ev):
        print(line)
    print(f"page: {render_mod.top_line(ev)} ({len(page)} bytes) -> {P['page']}")
    if a.dry_run:
        print("DRY RUN: nothing published, nothing sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
