"""Run the HQ desk end to end, or one half of it.

  python3 -m tools.hq_desk.run --location hq --stage data          pull + score, writes brief.json for drafting
  python3 -m tools.hq_desk.run --location hq --stage page [--prev <last page>] [--routines routines.json]
                                                                   merge + check drafts, render, decide the text
  python3 -m tools.hq_desk.run --location agc --dry-run            everything (no drafts), for a test

The script itself never publishes and never texts. In --dry-run it says so and prints what it would text.
Files (in /tmp/hq_desk unless HQ_DESK_DIR is set): raw.json, desk.json, brief.json, drafts.json (the model's),
hq_desk.html (the page), sms.txt (only when a text is due).
Exit 0 ok, 1 a draft is held by the copy checker (fix drafts.json, run --stage page again), 2 cannot read GHL.
"""
import argparse
import json
import os
import sys

from shared import et
from tools.hq_desk import profile as prof
from tools.hq_desk import pull as pull_mod
from tools.hq_desk import score as score_mod
from tools.hq_desk import drafts as drafts_mod
from tools.hq_desk import render as render_mod
from tools.hq_desk import alert as alert_mod


def paths(out_dir):
    return {k: os.path.join(out_dir, v) for k, v in {
        "raw": "raw.json", "desk": "desk.json", "brief": "brief.json", "drafts": "drafts.json",
        "page": "hq_desk.html", "sms": "sms.txt"}.items()}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def stage_data(p, P, now, max_deals, workers, routines=None):
    for k in ("drafts", "sms", "page"):
        if os.path.exists(P[k]):
            os.remove(P[k])          # never carry yesterday's drafts into today's page
    raw = pull_mod.pull(p, now=now, max_deals=max_deals, workers=workers,
                        log=lambda s: print("pull: " + s, file=sys.stderr))
    pull_mod.write_json(P["raw"], raw)
    if raw.get("fatal"):
        print("NO ACCESS: " + raw["fatal"])
        return 2
    desk = score_mod.build(raw, now=now, routines=routines)
    pull_mod.write_json(P["desk"], desk)
    b = score_mod.brief(desk)
    pull_mod.write_json(P["brief"], b, indent=None)
    c = desk["counts"]
    reds = [f["text"] for f in desk["health"] if f["level"] == "red"]
    print(f"data: {len(raw['opportunities'])} deals, {len(raw['contacts'])} contacts read, "
          f"{len(raw['errors'])} read errors")
    print(f"desk: {c['candidates']} leads need something ({c['hot']} hot, {c['deciding']} deciding, "
          f"{c['owed']} owed, {c['rebook']} rebook, {c['stale_replied']} replied waiting, "
          f"{c['warm_referral']} warm referral); {len(b['leads'])} in brief.json for drafting")
    print("red flags: " + (" | ".join(reds) if reds else "none"))
    return 0


def stage_page(p, P, prev, routines, dry_run):
    desk = load(P["desk"])
    if routines is not None:
        score_mod.apply_routines(desk, routines)
    held = 0
    if os.path.exists(P["drafts"]):
        try:
            got = load(P["drafts"])
        except ValueError as e:
            print(f"drafts: {P['drafts']} is not valid JSON ({e}). Fix it and run --stage page again.")
            return 1
        if not isinstance(got, dict):
            print("drafts: drafts.json must be one JSON object keyed by lead id. Fix it and run --stage page again.")
            return 1
        desk, report, held = drafts_mod.merge(desk, got)
        which = "copy_check" if drafts_mod.checker_cmd() else "basic check (copy_check not installed yet)"
        print(f"drafts: checked with {which}, {held} held")
        for line in report:
            print("  " + line)
    else:
        print("drafts: none")
    pull_mod.write_json(P["desk"], desk)
    page = render_mod.render(desk)
    with open(P["page"], "w", encoding="utf-8") as f:
        f.write(page)
    shown, _ = render_mod.visible_items(desk)
    print(f"page: {render_mod.top_line(desk, shown)} ({len(page)} bytes) -> {P['page']}")
    msg, why = alert_mod.decide(desk, alert_mod.read_prev_state(prev), p.get("artifact_url") or "")
    if msg:
        with open(P["sms"], "w", encoding="utf-8") as f:
            f.write(msg)
        print(("WOULD TEXT: " if dry_run else "TEXT: ") + msg)
    else:
        if os.path.exists(P["sms"]):
            os.remove(P["sms"])
        print("NO TEXT: " + why)
    if dry_run:
        print("DRY RUN: nothing published, nothing texted.")
    return 1 if held else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="HQ desk runner.")
    ap.add_argument("--location", default="hq")
    ap.add_argument("--stage", choices=["all", "data", "page"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prev", help="last published page (Artifact read) to tell what is new")
    ap.add_argument("--routines", help="JSON from list_triggers: [{name, status}] or {\"unavailable\": why}")
    ap.add_argument("--max-deals", type=int, default=150)
    ap.add_argument("--workers", type=int, default=pull_mod.WORKERS)
    ap.add_argument("--now", help="ISO time (tests)")
    ap.add_argument("--out-dir", default=prof.OUT_DIR)
    a = ap.parse_args(argv)
    p = prof.resolve(a.location)
    P = paths(a.out_dir)
    os.makedirs(a.out_dir, exist_ok=True)
    now = et.parse(a.now) if a.now else et.now_utc()
    routines = load(a.routines) if a.routines and os.path.exists(a.routines) else None
    code = 0
    if a.stage in ("all", "data"):
        code = stage_data(p, P, now, a.max_deals, a.workers, routines)
        if code:
            return code
    if a.stage in ("all", "page"):
        if not os.path.exists(P["desk"]):
            print("no desk.json yet: run --stage data first")
            return 2
        code = stage_page(p, P, a.prev, routines, a.dry_run)
    return code


if __name__ == "__main__":
    sys.exit(main())
