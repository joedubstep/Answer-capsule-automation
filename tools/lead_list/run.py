"""Lead List command line. Run from the repo root.

  python3 -m tools.lead_list.run sources
  python3 -m tools.lead_list.run find-download --state nc
  python3 -m tools.lead_list.run inspect --state fl --file <download or folder>
  python3 -m tools.lead_list.run review --state fl --out <out> --show names|no-email|sample [--limit 30]
  python3 -m tools.lead_list.run build --state fl --file <download or folder> [--file <another>]
        [--data <engine data/carehome>]
        [--out /tmp/lead_list_out] [--min-beds 40] [--no-web] [--no-search] [--sites extra_sites.csv]
        [--names names.csv] [--minutes 50] [--workers 8] [--variants AB] [--date YYYY-MM-DD]

build writes <out>/<state>/: review.csv, queue_additions.json, lead_facts_additions.json,
prospects_additions.json, summary.json, HOW-TO-LOAD.md. It never writes the engine or state repo.
--file takes one file, several (--file a.xlsx --file b.xlsx) or a folder: a state that will not export the whole
state at once (Florida: "dataset too large") is exported county by county or area by area into one folder.
Exit codes: 0 done, 2 bad input (missing file, unmapped column), 3 the network blocked the source download.
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import json
import os
import sys
import time

from . import common, dedupe, emails, filters, normalize, runway, tabular, web, website, writer
from .sources import REGISTRY, get as get_source


# ------------------------------------------------------------------ loading

DATA_EXT = (".csv", ".txt", ".tsv", ".xlsx", ".xls", ".json", ".htm", ".html", ".xml")


def expand_files(files):
    """--file values -> the data files they name. A folder gives every data file directly inside it."""
    if isinstance(files, str):
        files = [files] if files else []
    out = []
    for f in files or []:
        if os.path.isdir(f):
            for name in sorted(os.listdir(f)):
                path = os.path.join(f, name)
                if os.path.isfile(path) and name.lower().endswith(DATA_EXT) and not name.startswith(("~$", ".")):
                    out.append(path)
        elif os.path.exists(f):
            out.append(f)
        else:
            raise SystemExit(f"no such file: {f}")
    if files and not out:
        raise SystemExit(f"no data files (.csv, .xlsx, .xls, .txt, .json, .html) in {', '.join(files)}")
    return out


def _read_one(src, path_or_bytes, name):
    try:
        return tabular.load_rows(path_or_bytes, src.all_aliases(), name=name)
    except Exception as ex:  # noqa: BLE001  a file the reader cannot use (bad zip, bad XML...): say which and why
        raise SystemExit(f"{name}: cannot read it ({type(ex).__name__}: {ex})")


def load_sources(src, files=None, url=""):
    """-> [(label, headers, mapping, rows)], one per file, or raises SystemExit / web.Blocked."""
    paths = expand_files(files)
    if paths:
        return [(os.path.basename(p), *_read_one(src, p, p)) for p in paths]
    url = url or src.download_url
    if not url:
        raise SystemExit(f"{src.state}: no direct download link is known. {src.how_to}")
    data = web.fetch_bytes(url)
    return [(url, *_read_one(src, data, url))]


def normalize_files(src, parts):
    """Normalize every file's rows with its own column mapping. Overlapping exports (two counties' searches that
    both return a border home) give the same id twice: the first copy is kept, so each home counts once."""
    recs, seen = [], set()
    for _label, _headers, mapping, rows in parts:
        for r in normalize.normalize_all(src, rows, mapping):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            recs.append(r)
    return recs


def missing_fields(src, mapping):
    return [f for f in src.required if f not in mapping]


# ------------------------------------------------------------------ web step

def _load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _csv_map(path, col):
    """id -> value from a two-column CSV (id,<col>) written by Claude during review."""
    out = {}
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("id") and r.get(col) is not None:
                    out[r["id"].strip()] = r[col].strip()
    return out


def _extra_sites(path):
    return {k: v for k, v in _csv_map(path, "website").items() if v}


def web_one(rec, fetch_fn, extra_site, use_search):
    site = website.find(rec, fetch_fn, extra_site, use_search)
    found = []
    if site:
        found = emails.site_emails(site["website"], fetch_fn, site.get("html"), first=rec.get("first_name", ""),
                                   last=rec.get("last_name", ""))
    pick = emails.choose(found, site.get("website", ""), rec.get("list_email", ""), rec.get("first_name", ""),
                         rec.get("last_name", ""), rec.get("state", ""))
    return {"website": site.get("website", ""), "website_source": site.get("website_source", ""), **pick}


def web_step(recs, out_dir, fetch_fn=None, minutes=50, workers=8, use_search=True, sites_csv="", log=print):
    """Website + published email for each record. Results are cached per home in web_cache.json, so a second run
    continues where the first stopped. Returns 'done', 'partial' (time ran out) or 'blocked'."""
    fetch_fn = fetch_fn or web.Polite(web.fetch)
    website.SEARCH.update(off=False, why="", fails=0)
    cache_path = os.path.join(out_dir, "web_cache.json")
    cache = _load_cache(cache_path)
    extra = _extra_sites(sites_csv)
    todo = [r for r in recs if r["id"] not in cache or (r["id"] in extra and not cache[r["id"]].get("website"))]
    # Probe hosts that are always up (never a home's own site: one dead home domain must not stop the batch).
    probes = ("https://html.duckduckgo.com/html/?q=assisted+living", "https://www.wikipedia.org/")
    if todo and all(web.egress(u, fetch_fn) == "blocked" for u in probes):
        log("web step: BLOCKED (this session's network refuses the open web); no websites or emails looked up. "
            "Run the build where the web is open (Joey's PC Claude session).")
        status = "blocked"
    else:
        status = "done"
        stop_at = time.time() + minutes * 60
        done_n = 0

        def task(r):
            if time.time() > stop_at:
                return r["id"], None
            try:
                res = web_one(r, fetch_fn, extra.get(r["id"], ""), use_search)
            except web.Blocked:
                return r["id"], "blocked"
            except Exception:  # noqa: BLE001  a bad site or a refused search: not cached, so a re-run retries
                return r["id"], None
            return r["id"], res

        with cf.ThreadPoolExecutor(max(1, workers)) as ex:
            for pid, res in ex.map(task, todo):
                if res == "blocked":
                    status = "blocked"
                    continue
                if res is None:
                    status = "partial"
                    continue
                cache[pid] = {**res, "checked": dt.date.today().isoformat()}
                done_n += 1
                if done_n % 25 == 0:
                    writer.write_json(cache_path, cache, 0)
                    log(f"web step: {done_n} of {len(todo)} homes looked up")
        writer.write_json(cache_path, cache, 0)
        if website.SEARCH["fails"]:
            log(f"web step: the search engine refused {website.SEARCH['fails']} time(s)"
                f"{' and search was switched off' if website.SEARCH['off'] else ''}; those homes were left for the "
                "next run. Re-run later, or give Claude-found sites with --sites.")
            status = "partial"
    for r in recs:
        c = cache.get(r["id"])
        if c:
            r.update({k: c.get(k, "") for k in ("website", "website_source", "email", "email_source", "email_page")})
            r["emails_found"] = c.get("emails_found", [])
        elif r.get("list_email"):
            pick = emails.choose([], "", r["list_email"], r.get("first_name", ""), r.get("last_name", ""), r["state"])
            r.update({k: pick[k] for k in ("email", "email_source", "email_page")})
            r.setdefault("website", "")
            r.setdefault("website_source", "")
    return status


# ------------------------------------------------------------------ outputs

def how_to_load(src, summary, out_dir):
    s = summary
    bpath = os.path.abspath(out_dir)
    rw = s["runway"]
    runway_line = (f"Expected to pass the mailbox check: about {rw['expected_sendable']} homes, about "
                   f"{rw['days_added']} days of new homes at {rw['pace_per_day']} a day." if rw.get("days_added")
                   else f"Expected to pass the mailbox check: about {rw['expected_sendable']} homes (no send pace "
                        "was readable from carehome.db, so no days figure).")
    return f"""# How to load the {src.state} batch ({s['date']})

This folder holds a new batch of {s['counts']['queue_additions']} {src.state} homes for the cold-email engine. Nothing
has been loaded yet. A PC Claude session (or Joey) loads it in about 5 minutes.

## What is in this folder

| File | What it is |
|------|------------|
| `review.csv` | One row per home on the state list: kept or left out, and why. Sources for phone, name, website, email. |
| `queue_additions.json` | {s['counts']['queue_additions']} new `queue.json` entries (v3 copy, A/B variant, ranks below the current queue). |
| `lead_facts_additions.json` | The same homes for `lead_facts.json` (beds, care type, address, time zone, phone and its source). |
| `prospects_additions.json` | The same homes for `build/prospects.json` (contact name, email source, flags). |
| `summary.json` | The counts below. |

Counts: {s['counts']['on_list']} homes on the list, {s['counts']['assisted_living_40_plus']} assisted living with
{s['min_beds']}+ beds, {s['counts']['after_dedupe']} new to the campaign, {s['counts']['with_website']} with a
website, {s['counts']['with_email']} with a published email, {s['counts']['queue_additions']} ready to load.
{runway_line}

## Steps (Claude session on Joey's PC)

Paths: this tool lives in `C:\\dev\\aca` (Joey's public automation repo; `git clone --depth 1 -b
claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation C:\\dev\\aca` if it is not
there). The engine is `C:\\dev\\surven-outreach`. This batch folder is `{bpath}`; if it was built on another
machine, copy it to the PC and use that path instead.

1. In `C:\\dev\\surven-outreach`, get the latest state so nothing sent today is lost:
   `python tools/cloud_state.py pull`
2. In `C:\\dev\\aca`, dry run (prints how many homes go in and any duplicates found since the build):
   `python -m tools.lead_list.merge --batch "{bpath}" --data C:\\dev\\surven-outreach\\data\\carehome`
3. Show Joey the count and 10 random rows of `review.csv` where decision is `include`. Load only after his OK.
4. Write it (backups of the three files go into this folder first):
   `python -m tools.lead_list.merge --batch "{bpath}" --data C:\\dev\\surven-outreach\\data\\carehome --write`
5. In `C:\\dev\\surven-outreach`, publish the PC-owned files (the cloud run's files stay as they are):
   `python tools/cloud_state.py push-local queue.json lead_facts.json build/prospects.json`

## What happens next (automatic)

- The next GitHub Actions send run (`carehome run`, every 10 minutes in the send window) first loads `queue.json`
  into carehome.db, so the new homes appear there as `queued`.
- The nightly 03:15 UTC job runs `verify_mail`: it asks each home's mail server whether the mailbox exists.
  Only `valid` (or `published`) addresses get email 1, in the home's 7 to 10 AM local window, after every home
  already queued (the batch's ranks sit below them).
- `enrich_mail` then retries the ones that came back invalid, unknown or catch-all.
- The Google Sheet picks the new homes up from `build/prospects.json` on its next sync.

## Rules this batch follows

- 40+ licensed beds only (Joey, 10/23). Assisted living licenses only, active licenses only.
- Emails were printed by the home itself (its own website) or by the state list. No guessed addresses.
- Copy is the locked v3 sequence, word for word. Every email body passed the copy checker.
- To undo before step 5: copy the three files back from this folder's `backup-<time>` folder.
"""


def blocked_note(src, host_msg, out_dir):
    return f"""# {src.state} batch: not built (network blocked)

The build ran on {dt.date.today().isoformat()} in a cloud session whose network policy refuses the state's site:
`{host_msg}`. No homes were downloaded, so no batch was written. Nothing here is a real result.

## Run it where the web is open

On Joey's PC (any Claude session there has the open web), from the Answer-capsule-automation repo root:

1. Get the file: {src.how_to}
2. `python -m tools.lead_list.run inspect --state {src.code} --file <the file or folder>`
3. `python -m tools.lead_list.run build --state {src.code} --file <the file or folder> --data C:\\dev\\surven-outreach\\data\\carehome --out <folder>`
4. Follow the HOW-TO-LOAD.md the build writes.

Or allow these hosts in the cloud environment's network settings and re-run here: the state site
({website.domain(src.page_url)}), html.duckduckgo.com, and the homes' own websites (any host), which in practice
means the environment's full network access level.
"""


def build(args, fetch_fn=None, log=print):
    src = get_source(args.state)
    today = args.date or dt.date.today().isoformat()
    out_dir = os.path.join(args.out, src.code)
    os.makedirs(out_dir, exist_ok=True)
    data = common.find_data_dir(args.data)
    if not data:
        raise SystemExit("no engine data folder found: pass --data <engine>/data/carehome")
    ix = dedupe.Index.load(data)
    log(f"campaign index: {ix.counts}")
    names = _csv_map(getattr(args, "names", ""), "home")
    if not (args.file or args.url or src.download_url):
        log(f"{src.state}: no file given and no direct download link is known. {src.how_to}")
        return 2, {}
    try:
        parts = load_sources(src, args.file, args.url)
    except web.Blocked as ex:
        with open(os.path.join(out_dir, "RUN-STATUS.md"), "w", encoding="utf-8") as f:
            f.write(blocked_note(src, str(ex), out_dir))
        log(f"{src.state}: BLOCKED downloading the state list ({ex}). Wrote {out_dir}/RUN-STATUS.md")
        return 3, {}
    for label, headers, mapping, rows in parts:
        miss = missing_fields(src, mapping)
        if miss:
            log(f"{src.state}: {label} has no column for {', '.join(miss)}. Headers: {headers}. "
                f"Add the right header to {src.code}'s aliases (tools/lead_list/sources/) and run again.")
            return 2, {}
    recs = normalize_files(src, parts)
    label = ", ".join(p[0] for p in parts)
    label = label if len(label) <= 200 else f"{len(parts)} files ({parts[0][0]} ...)"
    log(f"{src.state}: {len(recs)} homes on the list ({label}); mapped columns: {parts[0][2]}")
    kept = filters.apply(src, recs, args.min_beds)
    al40 = len(kept)
    kept = dedupe.apply(ix, kept)
    after = len(kept)
    log(f"{src.state}: {al40} assisted living with {args.min_beds}+ beds, {after} new to the campaign")
    web_status = "skipped (--no-web)"
    if not args.no_web:
        web_status = web_step(kept, out_dir, fetch_fn, args.minutes, args.workers, not args.no_search, args.sites,
                              log)
    else:
        for r in kept:
            if r.get("list_email"):
                pick = emails.choose([], "", r["list_email"], r.get("first_name", ""), r.get("last_name", ""),
                                     r["state"])
                r.update({k: pick[k] for k in ("email", "email_source", "email_page")})
    with_site = sum(1 for r in kept if r.get("website"))
    have_email = []
    looked_up = _load_cache(os.path.join(out_dir, "web_cache.json")) if web_status in ("done", "partial") else {}
    for r in kept:
        if r.get("email"):
            have_email.append(r)
        else:
            r["decision"] = "exclude"
            r["reason"] = ("no published email found" if r["id"] in looked_up
                           else f"no email yet (web step {web_status})")
    with_email = len(have_email)
    have_email = dedupe.apply_email(ix, have_email)
    for r in have_email:  # names Claude or Joey fixed by hand after reading review.csv (--names id,home)
        if r["id"] in names:
            r["home"] = names[r["id"]].strip() or common.YOUR_HOME
            r["home_check"] = "set by review"
    queue, facts, people = writer.build(have_email, src, ix.min_rank, today, args.variants)
    writer.write_json(os.path.join(out_dir, "queue_additions.json"), queue, 1)
    writer.write_json(os.path.join(out_dir, "lead_facts_additions.json"), facts, 0)
    writer.write_json(os.path.join(out_dir, "prospects_additions.json"), people, 1)
    writer.write_review(os.path.join(out_dir, "review.csv"), recs)
    st = runway.stats(data)
    est = runway.batch_estimate(out_dir, st, args.pace)
    summary = {
        "state": src.state, "date": today, "source": label, "source_page": src.page_url, "min_beds": args.min_beds,
        "web_step": web_status,
        "counts": {"on_list": len(recs), "assisted_living_40_plus": al40, "after_dedupe": after,
                   "with_website": with_site, "with_email": with_email, "queue_additions": len(queue),
                   "variant_A": sum(q["variant"] == "A" for q in queue),
                   "variant_B": sum(q["variant"] == "B" for q in queue),
                   "named_greeting": sum(bool(q["first_name"]) for q in queue),
                   "your_home_fallback": sum(q["home"] == common.YOUR_HOME for q in queue)},
        "runway": est, "queue_now": st, "dedupe_index": ix.counts,
    }
    writer.write_json(os.path.join(out_dir, "summary.json"), summary, 1)
    with open(os.path.join(out_dir, "HOW-TO-LOAD.md"), "w", encoding="utf-8") as f:
        f.write(how_to_load(src, summary, out_dir))
    status_file = os.path.join(out_dir, "RUN-STATUS.md")
    if os.path.exists(status_file):
        os.remove(status_file)
    log(json.dumps({"state": src.state, **summary["counts"], "web_step": web_status,
                    "days_added": est["days_added"]}))
    return 0, summary


# ------------------------------------------------------------------ other commands

def cmd_inspect(args):
    src = get_source(args.state)
    try:
        parts = load_sources(src, args.file, args.url)
    except web.Blocked as ex:
        print(f"BLOCKED: {ex}. {src.how_to}")
        return 3
    bad = 0
    for label, headers, mapping, rows in parts:
        print(f"{src.state} ({label}): {len(rows)} rows")
        print("headers:", headers)
        for f in sorted(src.all_aliases()):
            print(f"  {f:<14} <- {mapping.get(f, '(not found)')}")
        miss = missing_fields(src, mapping)
        bad += bool(miss)
        print("required fields missing:", miss or "none")
    recs = normalize_files(src, [(lb, h, m, rows[:400]) for lb, h, m, rows in parts])
    kept = filters.apply(src, recs)
    print(f"sample of {len(recs)} homes (up to 400 rows per file): {len(kept)} pass the type, status and "
          f"{common.MIN_BEDS}+ bed filter")
    types = {}
    for r in recs:
        types[r.get("type") or "(no type column)"] = types.get(r.get("type") or "(no type column)", 0) + 1
    print("license types seen:", types)
    named = [r for r in recs if r.get("admin_raw")]
    print(f"greetings (administrator cell -> first name | home name), {len(named)} of {len(recs)} have an "
          f"administrator; admin_order is '{getattr(src, 'admin_order', 'first_last')}':")
    for r in named[:: max(1, len(named) // 8)][:8]:
        print(f"  {r['admin_raw']!r:<34} -> {r['first_name'] or '(none: Hi,)'} | {r['home']}")
    return 0 if not bad else 2


def review_rows(out_dir, show, limit=30, seed=None):
    """The few columns a review step needs, never the whole sheet (keeps the session's context small).
    show: 'names' (step 7), 'no-email' (step 6, biggest first) or 'sample' (step 8, random include rows)."""
    import random
    path = os.path.join(out_dir, "review.csv")
    if not os.path.exists(path):
        raise SystemExit(f"no review.csv in {out_dir}: run build first")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    inc = [r for r in rows if r.get("decision") == "include"]
    if show == "names":
        return [f"{r['id']} | {r['home']} | {r['facility']}" + (f" | {r['home_check']}" if r.get("home_check") else "")
                for r in inc][:limit]
    if show == "no-email":
        miss = [r for r in rows if r.get("reason") == "no published email found" and not r.get("website")]
        miss.sort(key=lambda r: -int(r.get("beds") or 0))
        return [f"{r['id']} | {r['facility']} | {r['city']} | {r['beds']} beds | phone {r['phone'] or 'none'}"
                for r in miss[:limit]]
    pick = random.Random(seed).sample(inc, min(limit, len(inc)))
    return [f"{r['first_name'] or '(Hi,)'} | {r['home']} | {r['city']} | {r['beds']} | {r['email_source']}"
            for r in pick]


def cmd_review(args):
    out_dir = os.path.join(args.out, get_source(args.state).code)
    lines = review_rows(out_dir, args.show, args.limit)
    print("\n".join(lines) or "(none)")
    return 0


def cmd_find_download(args):
    src = get_source(args.state)
    try:
        page = web.fetch(src.page_url)
    except web.Blocked as ex:
        print(f"BLOCKED: {ex}. Open {src.page_url} in a browser instead. {src.how_to}")
        return 3
    except OSError as ex:
        print(f"could not load {src.page_url}: {ex}")
        return 1
    hits = []
    for u, text in web.links(page.text, page.url or src.page_url, with_text=True):
        low = u.lower()
        if low.split("?")[0].endswith((".xlsx", ".xls", ".csv", ".txt", ".zip", ".json")) and \
                any(w in low or w in text.lower() for w in src.link_words):
            hits.append(f"{u}  ({text})" if text else u)
    print("\n".join(dict.fromkeys(hits)) or f"no data file links found on {src.page_url}. {src.how_to}")
    return 0


def main(argv=None):
    common.safe_stdout()
    ap = argparse.ArgumentParser(prog="lead_list")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources")
    for name in ("find-download", "inspect", "build"):
        p = sub.add_parser(name)
        p.add_argument("--state", required=True)
        if name != "find-download":
            p.add_argument("--file", action="append", default=[],
                           help="the state's download; repeat it, or give a folder, for several files")
            p.add_argument("--url", default="")
    rv = sub.add_parser("review", help="print the few columns a review step needs from review.csv")
    rv.add_argument("--state", required=True)
    rv.add_argument("--out", default=common.DEFAULT_OUT)
    rv.add_argument("--show", required=True, choices=["names", "no-email", "sample"])
    rv.add_argument("--limit", type=int, default=30)
    b = sub.choices["build"]
    b.add_argument("--data", default="")
    b.add_argument("--out", default=common.DEFAULT_OUT)
    b.add_argument("--min-beds", type=int, default=common.MIN_BEDS)
    b.add_argument("--no-web", action="store_true")
    b.add_argument("--no-search", action="store_true", help="only the state list's websites, no search engine")
    b.add_argument("--sites", default="", help="CSV of id,website found by Claude with WebSearch")
    b.add_argument("--names", default="", help="CSV of id,home: the name email 1 uses ('your home' allowed)")
    b.add_argument("--minutes", type=float, default=50)
    b.add_argument("--workers", type=int, default=8)
    b.add_argument("--variants", default="AB", choices=["AB", "A", "B"])
    b.add_argument("--pace", type=float, default=None)
    b.add_argument("--date", default="")
    a = ap.parse_args(argv)
    if a.cmd == "sources":
        for s in REGISTRY.values():
            print(f"{s.code}: {s.title}\n    page: {s.page_url}\n    get it: {s.how_to}")
        return 0
    if a.cmd == "find-download":
        return cmd_find_download(a)
    if a.cmd == "inspect":
        return cmd_inspect(a)
    if a.cmd == "review":
        return cmd_review(a)
    code, _ = build(a)
    return code


if __name__ == "__main__":
    sys.exit(main())
