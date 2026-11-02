"""Time Ledger runner: the commands the skill calls, in this order.

  python3 -m tools.time_ledger.run sql      --mode nightly|backfill|weekly [--page FILE --edited ISO] [--day YYYY-MM-DD]
  python3 -m tools.time_ledger.run more     existing|week_this|week_prev   (after each saved page of a SQL read)
  python3 -m tools.time_ledger.run prepare  --page FILE --existing FILE --mode nightly|backfill|weekly
                                            [--day YYYY-MM-DD] [--edited ISO]
  python3 -m tools.time_ledger.run build    [--labels FILE] [--evidence FILE] [--ghl]
  python3 -m tools.time_ledger.run finish   [--written N] [--dry-run] [--ghl]
  python3 -m tools.time_ledger.run weekly-sql [--day YYYY-MM-DD]
  python3 -m tools.time_ledger.run weekly   (--this FILE --prev FILE | --from-page) [--day YYYY-MM-DD]

Work files live in /tmp/time_ledger (TIME_LEDGER_DIR overrides). Python does the parsing, labeling, minutes,
dedupe and counting; the model only fetches, labels the low-confidence rows, gathers evidence for blank blocks
and writes what Python prepared. Nothing here calls Notion, Gmail or Calendar.
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import sys

from shared import et
from tools.time_ledger import classify as K
from tools.time_ledger import common as C
from tools.time_ledger import ghl_calls as G
from tools.time_ledger import infer as I
from tools.time_ledger import minutes as M
from tools.time_ledger import parse as P
from tools.time_ledger import report as R

BATCH = 50
EDIT_SIM = 0.6
JOEY_EMAIL_KEY = ("google", "joey_gmail")
# The only address the weekly report may ever go to is Joey's own Gmail (config google.joey_gmail). The repo is
# public, so the address itself is not written here: only its SHA-256, which a changed config cannot match.
ALLOWED_TO_SHA256 = "b78760b38cb5f8f87fc4bb5d3a0522a7fa93e3fdc01d6f7124bf6493f09e1b04"
WEEK_TEXT = 80                             # the weekly read keeps the first 80 characters of each action
NIGHTLY_BACK = 3                           # nightly also checks rows up to 3 days back that sit on the page
PAGE = 100                                 # the Notion SQL tool returns at most 100 rows a call, whatever the LIMIT
QUERIES = ("existing", "week_this", "week_prev")


# ---------------------------------------------------------------- helpers

def work_day(now=None):
    """The log day right now: before 4am ET still counts as the day before."""
    n = et.to_et(now or et.now_utc())
    d = n.date()
    return d - dt.timedelta(days=1) if n.hour < 4 else d


def ds_url(cfg):
    return (cfg.get("notion") or {}).get("action_log_ds") or ""


def ds_id(cfg):
    return ds_url(cfg).replace("collection://", "")


def window(mode, day, rows=None):
    """Days whose rows this run compares with Notion. Backfill: every day on the page. Nightly: the log day and the
    day before, widened to any day up to NIGHTLY_BACK days back that the copied sections hold (a blank block filled
    in two days later, or a heading fixed later, still gets written)."""
    dates = sorted({r["log_date"] for r in rows or []})
    hi = day.isoformat()
    if mode == "backfill":
        return (dates[0] if dates and dates[0] < hi else hi), hi
    lo = (day - dt.timedelta(days=1)).isoformat()
    back = (day - dt.timedelta(days=NIGHTLY_BACK)).isoformat()
    near = [d for d in dates if back <= d < lo]
    return (near[0] if near else lo), hi


def load_results(path):
    """SQL tool result (JSON with 'results'), a list, or nothing -> list of dicts."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except ValueError:
        start = raw.find("{")
        try:
            obj = json.loads(raw[start:]) if start >= 0 else []
        except ValueError:
            return []
    if isinstance(obj, dict):
        for k in ("results", "rows", "data"):
            if isinstance(obj.get(k), list):
                return obj[k]
        if isinstance(obj.get("text"), str):
            try:
                return load_results_text(obj["text"])
            except ValueError:
                return []
        return []
    if isinstance(obj, list):
        out = []
        for x in obj:
            if isinstance(x, dict) and isinstance(x.get("results"), list):
                out += x["results"]
            elif isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str):
                out += load_results_text(x["text"])
            elif isinstance(x, dict):
                out.append(x)
        return out
    return []


def load_results_text(t):
    obj = json.loads(t)
    return obj.get("results", []) if isinstance(obj, dict) else obj


# ---------------------------------------------------------------- SQL (read in pages of 100)
# Every query has an ORDER BY that ends in a unique column ("url", or the GROUP BY columns), so OFFSET 0, 100, 200
# ... walks the same order each call: no row is skipped and no page overlaps the one before.

def paged(sql, offset=0):
    """One page of a query: LIMIT 100 OFFSET <offset>."""
    return "%s LIMIT %d OFFSET %d" % (sql, PAGE, int(offset))


def _between(lo, hi):
    return ' WHERE "date:Date:start" >= \'%s\' AND "date:Date:start" <= \'%s\'' % (lo, hi)


def existing_sql(url, lo=None, hi=None):
    """The dedupe read: the keys already in the Action Log, for the days lo..hi (every day when lo is None)."""
    return ('SELECT "Key" AS k, "date:Date:start" AS d, "Block start" AS b, "Action" AS a, "url" AS u FROM "%s"%s '
            'ORDER BY "Key", "url"' % (url, _between(lo, hi) if lo else ""))


def week_this_sql(url, ws, we):
    """Weekly SQL A: every row of the week, action text cut to WEEK_TEXT characters."""
    return ('SELECT "date:Date:start" AS d, "Block start" AS b, "Minutes (est)" AS m, "Role" AS r, "Task" AS t, '
            '"Kind" AS k, "AI" AS ai, "Source" AS s, substr("Action", 1, %d) AS a, "url" AS u FROM "%s"%s '
            'ORDER BY "date:Date:start", "url"' % (WEEK_TEXT, url, _between(ws, we)))


def week_prev_sql(url, ps, pe):
    """Weekly SQL B: the week before, as totals per day, role and kind (one row per group, so 1, 2, 3 is unique)."""
    return ('SELECT "date:Date:start" AS d, "Role" AS r, "Kind" AS k, SUM("Minutes (est)") AS m, COUNT(*) AS n '
            'FROM "%s"%s AND "Source" = \'log\' AND "Role" != \'Not logged\' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3'
            % (url, _between(ps, pe)))


def page_path(name, n):
    return C.wpath("%s_%02d.json" % (name, n))


def page_files(name):
    """The saved pages of one query in order (<name>_01.json, <name>_02.json ...), up to the first gap."""
    out = []
    while os.path.exists(page_path(name, len(out) + 1)):
        out.append(page_path(name, len(out) + 1))
    return out


def new_query(name, sql):
    """Remember a query for `more` and clear any pages or merged file a rerun left behind."""
    for p in page_files(name) + [C.wpath(name + ".json")]:
        if os.path.exists(p):
            os.remove(p)
    q = C.read_json(C.wpath("queries.json"), {}) or {}
    q[name] = sql
    C.write_json(C.wpath("queries.json"), q)


def merge_pages(pages):
    """Pages of one query -> one list. A row that shows up twice (same url) is kept once."""
    seen, out = set(), []
    for rows in pages:
        for r in rows:
            u = r.get("u") if isinstance(r, dict) else None
            if u:
                if u in seen:
                    continue
                seen.add(u)
            out.append(r)
    return out


def _sig(text):
    return set(C.tokens(text))


def _sim(a, b):
    sa, sb = _sig(a), _sig(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def unmatched_rows(existing, page_rows):
    """Notion rows whose key matches nothing on the page any more: the text was edited or the date label was
    fixed. Only these may stand in for a 'new' row, and each one only once."""
    keys = {r["key"] for r in page_rows}
    out = []
    for x in existing:
        k = str(x.get("k") or x.get("Key") or "")
        a = x.get("a") or x.get("Action") or ""
        if k and k not in keys and a and a != C.BLANK_TEXT and not a.endswith("(inferred)"):
            out.append({"d": str(x.get("d") or "")[:10], "b": x.get("b") or "", "a": a, "used": False})
    return out


def take_orphan(orphans, r):
    """Mark and return True when an orphan Notion row is this row before an edit (same day and block, similar
    words) or before a date fix (same block and words, a day or two away)."""
    if r["type"] != "action":
        return False
    label, text = r.get("block_label") or "", r["action_text"]
    norm = C.norm_for_key(text)
    best = None
    for o in orphans:
        if o["used"] or o["b"] != label:
            continue
        try:
            gap = abs((C.parse_day(o["d"]) - C.parse_day(r["log_date"])).days)
        except ValueError:
            continue
        if gap == 0 and _sim(o["a"], text) >= EDIT_SIM:
            best = o
            break
        if 0 < gap <= 2 and C.norm_for_key(o["a"]) == norm and best is None:
            best = o
    if best is not None:
        best["used"] = True
        return True
    return False


def notion_props(r):
    title = r["action_text"] if r["type"] != "blank" else C.BLANK_TEXT
    title = (title or C.BLANK_TEXT)[:200]
    return {
        "Action": title,
        "date:Date:start": r["log_date"],
        "date:Date:is_datetime": 0,
        "Block start": r.get("block_label") or "",
        "Minutes (est)": float(r.get("minutes") or 0.0),
        "Role": r["role"],
        "Task": r.get("task") or "",
        "Kind": r["kind"],
        "AI": "__YES__" if r.get("ai") else "__NO__",
        "Confidence": float(r.get("confidence") or 0.0),
        "Source": r.get("source") or "log",
        "Key": r["key"],
    }


def _state():
    return C.read_json(C.wpath("state.json"), {}) or {}


# ---------------------------------------------------------------- stages

def cmd_sql(a, cfg):
    day = C.parse_day(a.day) if a.day else work_day()
    url = ds_url(cfg)
    rows = None
    if a.page:
        with open(a.page, encoding="utf-8") as f:
            rows = P.parse_page(f.read(), a.edited, today=day)["rows"]
    if a.mode == "backfill" and not rows:
        q = existing_sql(url)                 # no page to go by: every row in the database
        lo, hi = "0000-01-01", day.isoformat()
    else:
        lo, hi = window(a.mode, day, rows)
        q = existing_sql(url, lo, hi)
    if rows is not None and not rows:
        print("NO LOG FOUND: no '15 min log' heading on the page.")
    new_query("existing", q)
    C.write_json(C.wpath("state.json"), {"mode": a.mode, "day": day.isoformat(), "sql_window": [lo, hi]})
    print("LOG DAY: %s (%s)" % (day.isoformat(), day.strftime("%A")))
    print("WEEKLY REPORT DUE: %s" % ("yes" if day.weekday() == 6 else "no"))
    print("DATA SOURCE: %s" % url)
    print("SQL: %s" % paged(q, 0))
    print("SAVE THE RESULT TO: %s" % page_path("existing", 1))
    print("THEN RUN: python3 -m tools.time_ledger.run more existing   (after every page, until ALL PAGES READ)")
    return 0


def cmd_more(a, cfg):
    """After each saved page: a full page (100 rows) means there may be more, so print the next page's SQL. A
    short page is the last one: join every page into <name>.json for the next step."""
    base = (C.read_json(C.wpath("queries.json"), {}) or {}).get(a.name)
    if not base:
        print("NO QUERY: run the %s step first." % ("sql" if a.name == "existing" else "weekly-sql"))
        return 2
    files = page_files(a.name)
    if not files:
        print("NO PAGE SAVED: save the first page's result to %s" % page_path(a.name, 1))
        return 2
    pages = [load_results(p) for p in files]
    n = len(files)
    if len(pages[-1]) >= PAGE:
        print("MORE: page %d has %d rows, so there may be more. Run the next page:" % (n, len(pages[-1])))
        print("SQL: %s" % paged(base, n * PAGE))
        print("SAVE THE RESULT TO: %s" % page_path(a.name, n + 1))
        print("THEN RUN: python3 -m tools.time_ledger.run more %s" % a.name)
        return 0
    rows = merge_pages(pages)
    out = C.wpath(a.name + ".json")
    C.write_json(out, {"results": rows, "pages": n})
    print("ALL PAGES READ: %d row(s) in %d page(s) -> %s" % (len(rows), n, out))
    return 0


def missing(*paths):
    """A results file named but not there would read as 'nothing in Notion': stop instead."""
    gone = [p for p in paths if p and not os.path.exists(p)]
    for p in gone:
        print("NOT FOUND: %s. Read every page of the SQL first (run `more` until ALL PAGES READ)." % p)
    return bool(gone)


def cmd_prepare(a, cfg):
    if missing(a.existing):
        return 2
    with open(a.page, encoding="utf-8") as f:
        raw = f.read()
    day = C.parse_day(a.day) if a.day else work_day()
    res = P.parse_page(raw, a.edited, today=day)
    rows = res["rows"]
    if not rows:
        print("NO LOG FOUND: no '15 min log' heading on the page.")
        C.write_json(C.wpath("state.json"), {"mode": a.mode, "day": day.isoformat(), "empty": True})
        return 3
    M.estimate(rows)
    model = K.load_model()
    for r in rows:
        K.label_row(r, model)
        r["source"] = "log"
    lo, hi = window(a.mode, day, rows)
    sw = _state().get("sql_window")
    if sw and len(sw) == 2:                   # never treat a day as new that the Notion read did not cover
        lo, hi = max(lo, sw[0]), min(hi, sw[1])
    win = [r for r in rows if lo <= r["log_date"] <= hi]
    existing = load_results(a.existing)
    have = {str(x.get("k") or x.get("Key") or "") for x in existing}
    have.discard("")
    orphans = unmatched_rows(existing, rows)
    new, edited, blanks_new = [], 0, []
    for r in win:
        if r["key"] in have:
            continue
        if r["type"] == "blank":
            if I.block_keys(r) & have:
                continue
            blanks_new.append(r)
            new.append(r)
            continue
        if take_orphan(orphans, r):
            edited += 1                       # the page text or its date label changed; Notion already has it
            continue
        new.append(r)
    need = []
    by_block = {}
    for r in win:
        by_block.setdefault((r["log_date"], r["block_index"]), []).append(r)
    for r in new:
        if r["type"] == "action" and r.get("needs_label"):
            sibs = [x["action_text"] for x in by_block[(r["log_date"], r["block_index"])]
                    if x is not r and x["type"] == "action"][:3]
            need.append({"key": r["key"], "date": r["log_date"], "block": r.get("block_label"),
                         "text": r["action_text"], "same_block": sibs,
                         "guess": {"role": r["role"], "task": r["task"], "kind": r["kind"], "ai": r["ai"]},
                         "top3": r.get("role_top3")})
    wins = I.blank_windows(blanks_new)
    cals = ["primary"] + [c for c in [(cfg.get("google") or {}).get("surven_calendar")] if c]
    plan = I.evidence_plan(wins, cals) if wins else []
    C.write_json(C.wpath("page_rows.json"), rows)
    C.write_json(C.wpath("rows_window.json"), win)
    C.write_json(C.wpath("new_rows.json"), new)
    C.write_json(C.wpath("needs_label.json"), need)
    C.write_json(C.wpath("evidence_plan.json"), plan)
    C.write_json(C.wpath("state.json"), {"mode": a.mode, "day": day.isoformat(), "window": [lo, hi],
                                         "edited": res["edited"], "new": len(new), "need_label": len(need),
                                         "blank_windows": len(wins), "skipped_edits": edited})
    for s in res["sections"]:
        in_win = (s["resolved"] <= hi and s.get("last_day", s["resolved"]) >= lo) or lo <= s["heading_date"] <= hi
        if in_win and (s["suspect"] or s["resolved"] != s["heading_date"]):
            span = s["resolved"] if s.get("last_day", s["resolved"]) == s["resolved"] else "%s to %s" % (
                s["resolved"], s["last_day"])
            print("DATE CHECK: '%s' -> %s (%s)" % (s["heading"], span, "; ".join(s["notes"]) or "flagged"))
    counts = P.day_counts(win)
    for d in sorted(counts):
        c = counts[d]
        print("DAY %s: %d rows (%d blocks, %d blank, %d breaks)" % (d, c["rows"], c["blocks"], c["blank"], c["breaks"]))
    print("WINDOW %s to %s: %d rows parsed, %d already in Notion, %d edited or re-dated (kept the first version), "
          "%d new" % (
        lo, hi, len(win), sum(1 for r in win if r["key"] in have), edited, len(new)))
    if not new:
        print("NOTHING NEW")
        return 0
    print("NEED LABEL: %d row(s) -> %s" % (len(need), C.wpath("needs_label.json")))
    print("BLANK WINDOWS: %d -> evidence plan %s" % (len(wins), C.wpath("evidence_plan.json")))
    return 0


VALID = {"role": set(C.ROLES) | {C.NOT_LOGGED}, "kind": set(C.KINDS) | {C.NOT_LOGGED}}


def apply_labels(rows, labels):
    n = 0
    for r in rows:
        lab = labels.get(r["key"]) if isinstance(labels, dict) else None
        if not isinstance(lab, dict):
            continue
        ok = False
        for f in ("role", "kind"):
            v = lab.get(f)
            if v in VALID[f]:
                r[f] = v
                ok = True
        if isinstance(lab.get("task"), str) and lab["task"].strip():
            r["task"] = lab["task"].strip()[:80]
        if isinstance(lab.get("ai"), bool):
            r["ai"] = lab["ai"]
        if ok:
            r["labeled_by"] = "claude"
            r["needs_label"] = False
            n += 1
    return n


def ghl_day(day_iso, use):
    if not use:
        return None
    p = C.wpath("ghl_calls_%s.json" % day_iso)
    data = C.read_json(p)
    if data is None:
        data = G.pull(C.parse_day(day_iso))
        C.write_json(p, data)
    return data


def cmd_build(a, cfg):
    st = _state()
    new = C.read_json(C.wpath("new_rows.json"), []) or []
    labels = C.read_json(a.labels, {}) if a.labels else {}
    labeled = apply_labels(new, labels or {})
    unlabeled = sum(1 for r in new if r["type"] == "action" and r.get("needs_label"))
    evidence = C.read_json(a.evidence, []) if a.evidence else []
    blanks = [r for r in new if r["type"] == "blank"]
    ghl = {}
    if a.ghl:
        for d in sorted({r["log_date"] for r in blanks}):
            ghl[d] = ghl_day(d, True)
    inferred = I.infer(blanks, evidence, ghl) if blanks else []
    filled = {(r["log_date"], r["block_index"]) for r in inferred}
    out = [r for r in new if not (r["type"] == "blank" and (r["log_date"], r["block_index"]) in filled)] + inferred
    out.sort(key=lambda r: (r["log_date"], r["block_index"], r["position"]))
    C.write_json(C.wpath("inferred_rows.json"), inferred)
    C.write_json(C.wpath("write_rows.json"), out)
    bdir = C.wpath("batches")
    os.makedirs(bdir, exist_ok=True)
    for old in glob.glob(os.path.join(bdir, "batch_*.json")):
        os.remove(old)
    files = []
    for i in range(0, len(out), BATCH):
        p = os.path.join(bdir, "batch_%02d.json" % (i // BATCH + 1))
        C.write_json(p, {"parent": {"type": "data_source_id", "data_source_id": ds_id(cfg)},
                         "pages": [{"properties": notion_props(r)} for r in out[i:i + BATCH]]})
        files.append(p)
    st.update({"to_write": len(out), "labeled_by_claude": labeled, "still_unlabeled": unlabeled,
               "inferred": len(inferred), "batches": files})
    C.write_json(C.wpath("state.json"), st)
    gl = [d for d, g in ghl.items() if g and g.get("unavailable")]
    if gl:
        print("GHL: %s" % ghl[gl[0]]["unavailable"])
    print("LABELS APPLIED: %d (%d low-confidence row(s) kept the classifier's guess)" % (labeled, unlabeled))
    print("INFERRED: %d row(s) for %d blank block(s)" % (len(inferred), len(filled)))
    print("TO WRITE: %d row(s) in %d batch file(s) -> parent data_source_id %s" % (len(out), len(files), ds_id(cfg)))
    for p in files:
        print("BATCH: %s" % p)
    return 0


def merged_rows():
    """Every parsed row with the final labels (Claude's where it labeled), plus the inferred rows."""
    page = C.read_json(C.wpath("page_rows.json"), []) or []
    final = C.read_json(C.wpath("write_rows.json"), []) or []
    by_key = {r["key"]: r for r in final}
    rows = [by_key.get(r["key"], r) for r in page]
    rows += [r for r in final if r.get("source") == "inferred"]
    return [R.norm_row(r) for r in rows]


def cmd_finish(a, cfg):
    st = _state()
    if st.get("empty"):
        print("Time Ledger: no 15-minute log found on the To-Do page.")
        return 0
    day = st.get("day") or work_day().isoformat()
    d = R.daily(merged_rows(), day)
    written = None if a.dry_run else (a.written if a.written is not None else st.get("to_write", 0))
    line = R.daily_line(d, written)
    g = ghl_day(day, a.ghl)
    if g and not g.get("unavailable"):
        s = G.summary(g)
        if s["dials"]:
            line = line[:-1] + "; GoHighLevel: %d dials, %d answered, %s talk min." % (
                s["dials"], s["answered"], s["talk_min"])
    if st.get("mode") == "backfill":
        line = line[:-1] + "; backfill window %s to %s." % tuple(st.get("window", ["?", "?"]))
    if a.dry_run:
        line = line[:-1] + " (dry run: nothing written, %d row(s) would be added)." % st.get("to_write", st.get("new", 0))
    st["written"] = 0 if a.dry_run else (written or 0)
    C.write_json(C.wpath("state.json"), st)
    upd = et.now_et().strftime("%b %d, %I:%M %p ET")
    C.write_text(C.wpath("daily.md"), R.daily_markdown(d))
    C.write_text(C.wpath("daily.html"), R.daily_html(d, upd))
    print(line)
    return 0


def weekly_days(day):
    """The week to report: Mon..Sun holding `day` when it is Sunday, otherwise the last full week."""
    if day.weekday() == 6:
        return R.week_bounds(day)
    return R.week_bounds(day - dt.timedelta(days=day.weekday() + 1))


def cmd_weekly_sql(a, cfg):
    day = C.parse_day(a.day) if a.day else work_day()
    ws, we = weekly_days(day)
    ps, pe = ws - dt.timedelta(days=7), we - dt.timedelta(days=7)
    url = ds_url(cfg)
    qa, qb = week_this_sql(url, ws, we), week_prev_sql(url, ps, pe)
    new_query("week_this", qa)
    new_query("week_prev", qb)
    print("WEEK: %s to %s (compared with %s to %s)" % (ws, we, ps, pe))
    print("SQL A (this week, save page 1 to %s): %s" % (page_path("week_this", 1), paged(qa, 0)))
    print("SQL B (week before, save page 1 to %s): %s" % (page_path("week_prev", 1), paged(qb, 0)))
    print("THEN RUN: python3 -m tools.time_ledger.run more week_this (and more week_prev) after every page, "
          "until each prints ALL PAGES READ")
    return 0


def allowed_recipient(addr):
    a = (addr or "").strip().lower()
    return bool(a) and hashlib.sha256(a.encode("utf-8")).hexdigest() == ALLOWED_TO_SHA256


def just_written(sql_rows, ws, we):
    """Rows this run wrote a moment ago that the Notion SQL read does not show yet (its index can lag a little).
    Batches are written in order, so the first `written` rows of write_rows.json are in Notion."""
    st = _state()
    n = int(st.get("written") or 0)
    if not n:
        return []
    have = {}
    for r in sql_rows:
        k = (r["date"], r["block"], r["action"][:WEEK_TEXT])
        have[k] = have.get(k, 0) + 1
    out = []
    for r in (C.read_json(C.wpath("write_rows.json"), []) or [])[:n]:
        x = R.norm_row(r)
        if x["action"] == "" and x["type"] == "blank":
            x["action"] = C.BLANK_TEXT
        if not (ws.isoformat() <= x["date"] <= we.isoformat()):
            continue
        k = (x["date"], x["block"], x["action"][:WEEK_TEXT])
        if have.get(k):
            have[k] -= 1
            continue
        out.append(x)
    if out:
        print("ADDED %d row(s) written this run that the SQL read did not show yet" % len(out))
    return out


def cmd_weekly(a, cfg):
    day = C.parse_day(a.day) if a.day else work_day()
    ws, we = weekly_days(day)
    ps, pe = ws - dt.timedelta(days=7), we - dt.timedelta(days=7)
    if a.from_page:
        rows = merged_rows()
        this = [r for r in rows if ws.isoformat() <= r["date"] <= we.isoformat()]
        prev = [r for r in rows if ps.isoformat() <= r["date"] <= pe.isoformat()]
        hist = R.distraction_by_day([r for r in rows if r["date"] < ps.isoformat()])
    else:
        if missing(a.this, a.prev):
            return 2
        this = [R.norm_row(r) for r in load_results(a.this)]
        this += just_written(this, ws, we)
        prev = [R.norm_row(dict(r, s="log", a="(week total)")) for r in load_results(a.prev)]
        hist = None
    w = R.weekly(this, prev, ws, we, history=hist)
    title = R.weekly_title(w)
    upd = et.now_et().strftime("%b %d, %I:%M %p ET")
    md = R.weekly_markdown(w)
    C.write_text(C.wpath("weekly.md"), md)
    C.write_text(C.wpath("weekly.txt"), R.weekly_text(w))
    C.write_text(C.wpath("weekly.html"), R.weekly_html(w, upd))
    C.write_json(C.wpath("weekly.json"), w)
    to = (cfg.get(JOEY_EMAIL_KEY[0]) or {}).get(JOEY_EMAIL_KEY[1]) or ""
    if not allowed_recipient(to):
        print("EMAIL BLOCKED: google.joey_gmail in config is not Joey's own address, so no email will be prepared.")
        to = ""
    C.write_json(C.wpath("email.json"), {"to": [to] if to else [], "subject": title, "body": R.weekly_text(w),
                                          "htmlBody": R.weekly_html(w, upd)})
    home = (cfg.get("notion") or {}).get("automations_home") or ""
    C.write_json(C.wpath("notion_page.json"), {"parent": {"type": "page_id", "page_id": home},
                                               "pages": [{"properties": {"title": title}, "icon": "⏱️",
                                                          "content": md}]})
    print("WEEKLY READY: %s" % title)
    print("HEADLINE: %d of 7 days logged, about %s of work, selling %s, distraction %s, %d automation candidate(s), "
          "%d blank block(s)." % (w["days_logged"], C.hours(w["work_minutes"]), C.hours(w["selling_minutes"]),
                                  C.hours(w["distraction_minutes"]), len(w["candidates"]), w["blank_blocks"]))
    print("NOTION PAGE: %s (parent page %s)" % (C.wpath("notion_page.json"), home))
    print("EMAIL: %s (to %s only)" % (C.wpath("email.json"), to or "nobody: google.joey_gmail is empty"))
    if a.dry_run:
        print("")
        print(R.weekly_text(w))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sql")
    s.add_argument("--mode", choices=("nightly", "backfill", "weekly"), default="nightly")
    s.add_argument("--day")
    s.add_argument("--page", help="the copied log (page.md): widens the nightly window to the days it holds")
    s.add_argument("--edited")
    mo = sub.add_parser("more")
    mo.add_argument("name", choices=QUERIES)
    p = sub.add_parser("prepare")
    p.add_argument("--page", required=True)
    p.add_argument("--existing")
    p.add_argument("--mode", choices=("nightly", "backfill", "weekly"), default="nightly")
    p.add_argument("--day")
    p.add_argument("--edited")
    b = sub.add_parser("build")
    b.add_argument("--labels")
    b.add_argument("--evidence")
    b.add_argument("--ghl", action="store_true")
    f = sub.add_parser("finish")
    f.add_argument("--written", type=int)
    f.add_argument("--dry-run", action="store_true")
    f.add_argument("--ghl", action="store_true")
    ws = sub.add_parser("weekly-sql")
    ws.add_argument("--day")
    w = sub.add_parser("weekly")
    w.add_argument("--this")
    w.add_argument("--prev")
    w.add_argument("--from-page", action="store_true")
    w.add_argument("--day")
    w.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cfg = C.load_config()
    fn = {"sql": cmd_sql, "more": cmd_more, "prepare": cmd_prepare, "build": cmd_build, "finish": cmd_finish,
          "weekly-sql": cmd_weekly_sql, "weekly": cmd_weekly}[a.cmd]
    if a.cmd == "weekly" and not a.from_page and not (a.this and a.prev):
        ap.error("weekly needs --this and --prev, or --from-page")
    return fn(a, cfg)


if __name__ == "__main__":
    sys.exit(main())
