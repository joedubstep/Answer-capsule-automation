"""Daily summary and weekly report from Action Log rows. Plain English, no em dashes.

Rows come from this run's parse (tools.time_ledger.run) or from the Notion Action Log (SQL results with the
short column names d, b, m, r, t, k, ai, s, a). Python does all the counting; nothing here calls the network.

Weekly report contents: minutes by role vs the week before, selling time, distraction minutes and the streak of
days under 20 distraction minutes, the top 5 time sinks, actions that repeat 3+ times in the week on 2 or more
days (automation candidates; one task continued 3 times in one sitting is not a repeat), and the count of blank
blocks. Output: markdown (for Notion), plain text and HTML (for the email).
"""
import datetime as dt
import html
import re

from tools.time_ledger import common as C

DISTRACTION_LIMIT = 20.0
REPEAT_MIN = 3
GENERIC_TASKS = {"", "Other", C.NOT_LOGGED, C.BREAK_TASK, "Not logged"}
FILLER = set("""spent about minute minutes min hour hours freak freaking fuck fucking okay some more another again
still continue continu keep start finish done thing stuff couple bit lot way also try trie tried""".split())
FILLER = {C.stem(w) for w in FILLER} | FILLER
PALETTE = {"cream": "#f2eee3", "paper": "#faf7ef", "sage": "#4e6242", "ink": "#181b18", "hair": "#c8c1b1"}


# ---------------------------------------------------------------- rows

def _yes(v):
    return v is True or str(v).strip().lower() in ("__yes__", "yes", "true", "1")


def norm_row(r):
    """Pipeline row or Notion SQL row -> one flat shape."""
    if "log_date" in r:
        return {"date": r["log_date"], "block": r.get("block_label") or r.get("block_start") or "",
                "minutes": float(r.get("minutes") or 0), "role": r.get("role") or C.NOT_LOGGED,
                "task": r.get("task") or "", "kind": r.get("kind") or C.NOT_LOGGED, "ai": bool(r.get("ai")),
                "source": r.get("source") or "log", "action": r.get("action_text") or "",
                "type": r.get("type") or "action"}
    g = lambda *ks: next((r[k] for k in ks if k in r and r[k] is not None), None)   # noqa: E731
    action = g("a", "Action") or ""
    role = g("r", "Role") or C.NOT_LOGGED
    task = g("t", "Task") or ""
    typ = "action"
    if action == C.BLANK_TEXT:
        typ = "blank"
    elif role == C.NOT_LOGGED:
        typ = "break" if task == C.BREAK_TASK else "blank"
    return {"date": str(g("d", "date:Date:start", "Date") or "")[:10], "block": g("b", "Block start") or "",
            "minutes": float(g("m", "Minutes (est)") or 0), "role": role, "task": task,
            "kind": g("k", "Kind") or C.NOT_LOGGED, "ai": _yes(g("ai", "AI")), "source": g("s", "Source") or "log",
            "action": action, "type": typ}


def dedupe(rows):
    """One block filled in later: keep its logged rows, drop the blank row and any guessed (inferred) rows."""
    by_block = {}
    for r in rows:
        by_block.setdefault((r["date"], r["block"]), []).append(r)
    out = []
    for key, rs in by_block.items():
        has_log = any(x["source"] == "log" and x["type"] in ("action", "break") for x in rs)
        has_inf = any(x["source"] == "inferred" for x in rs)
        for x in rs:
            if has_log and (x["source"] == "inferred" or x["type"] == "blank"):
                continue
            if has_inf and x["type"] == "blank":
                continue
            out.append(x)
    return out


def is_work(r):
    return r["type"] == "action" and r["role"] != C.NOT_LOGGED


KIND_LABEL = {"Outreach": "Outreach and calls", "Selling": "Sales calls", "Client work": "Client work",
              "Offer": "Offer work", "Learning": "Learning", "Personal": "Personal", "Distraction": "Distractions",
              "Tools": "Claude and tools", "Planning": "Planning", "Data sale": "Data sale",
              "Marketing": "Marketing", "Admin": "Admin", "SOPs": "SOPs", "Fixes": "Fixes"}


def group_label(r):
    if r["task"] not in GENERIC_TASKS:
        return r["task"]
    return KIND_LABEL.get(r["kind"]) or "%s (other)" % r["role"]


def signature(text):
    return frozenset(t for t in C.tokens(text) if t not in FILLER and len(t) > 1)


def clusters(rows, min_sim=0.5):
    """Greedy clusters of similar actions (token Jaccard)."""
    out = []
    for r in rows:
        sig = signature(r["action"])
        if not sig:
            continue
        best, bs = None, 0.0
        for c in out:
            inter = len(sig & c["sig"])
            if not inter:
                continue
            j = inter / float(len(sig | c["sig"]))
            if j > bs:
                best, bs = c, j
        if best is not None and bs >= min_sim:
            best["rows"].append(r)
            best["sig"] = best["sig"] | sig if len(best["sig"]) < 6 else best["sig"]
        else:
            out.append({"sig": sig, "rows": [r]})
    for c in out:
        texts = sorted((x["action"] for x in c["rows"]), key=lambda t: (len(t), t))
        c["label"] = texts[0] if texts else ""
        c["count"] = len(c["rows"])
        c["minutes"] = round(sum(x["minutes"] for x in c["rows"]), 1)
        roles = {}
        for x in c["rows"]:
            roles[x["role"]] = roles.get(x["role"], 0) + 1
        c["role"] = max(roles, key=roles.get)
        c["days"] = len({x["date"] for x in c["rows"]})
    return out


def _dayname(d):
    x = C.parse_day(d)
    return "%s %s" % (x.strftime("%a"), C.md_label(x))


def _short(t, n=70):
    """One line, at most n characters, and no long dashes (Joey's own words can hold them; the report may not)."""
    t = re.sub(r"\s*[\u2014\u2013]\s*", " - ", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 3].rstrip() + "..."


# ---------------------------------------------------------------- numbers

def role_minutes(rows):
    out = {}
    for r in rows:
        if is_work(r) and r["source"] == "log":
            out[r["role"]] = out.get(r["role"], 0.0) + r["minutes"]
    return out


def distraction_by_day(rows):
    out = {}
    for r in rows:
        if r["type"] == "action":
            out.setdefault(r["date"], 0.0)
            if r["kind"] == "Distraction":
                out[r["date"]] += r["minutes"]
    return out


def streak(dist_by_day, upto):
    """Days under the limit, counting back from `upto` over logged days (days with no log are skipped)."""
    n, broke = 0, False
    for d in sorted((d for d in dist_by_day if d <= upto), reverse=True):
        if dist_by_day[d] < DISTRACTION_LIMIT:
            n += 1
        else:
            broke = True
            break
    return n, broke


def blank_blocks(rows):
    blocks = {(r["date"], r["block"]) for r in rows if r["type"] == "blank" or r["source"] == "inferred"}
    inferred = {(r["date"], r["block"]) for r in rows if r["source"] == "inferred"}
    return len(blocks), len(inferred)


def time_sinks(rows, n=5):
    groups = {}
    for r in rows:
        if not is_work(r) or r["source"] != "log":
            continue
        g = groups.setdefault(group_label(r), {"minutes": 0.0, "count": 0, "examples": {}})
        g["minutes"] += r["minutes"]
        g["count"] += 1
        g["examples"][r["action"]] = g["examples"].get(r["action"], 0.0) + r["minutes"]
    out = []
    for label, g in sorted(groups.items(), key=lambda kv: -kv[1]["minutes"])[:n]:
        ex = max(g["examples"], key=g["examples"].get) if g["examples"] else ""
        out.append({"label": label, "minutes": round(g["minutes"], 1), "count": g["count"], "example": ex})
    return out


def automation_candidates(rows):
    work = [r for r in rows if is_work(r) and r["source"] == "log" and r["kind"] not in ("Distraction", "Personal")
            and r["role"] != "Personal"]
    cs = [c for c in clusters(work) if c["count"] >= REPEAT_MIN and c["days"] >= 2]
    out = [{"label": c["label"], "count": c["count"], "minutes": c["minutes"], "role": c["role"],
            "days": c["days"]} for c in cs]
    covered = {id(x) for c in cs for x in c["rows"]}
    # second pass: the same opening words on different topics ("send prompt ...", "ask Claude ...")
    groups = {}
    for r in work:
        if id(r) in covered:
            continue
        t = [x for x in C.tokens(r["action"]) if x not in FILLER]
        if len(t) >= 2:
            groups.setdefault(tuple(t[:2]), []).append(r)
    for key, rs in groups.items():
        days = len({x["date"] for x in rs})
        if len(rs) >= REPEAT_MIN and days >= 2:
            roles = {}
            for x in rs:
                roles[x["role"]] = roles.get(x["role"], 0) + 1
            out.append({"label": "%s ... (different topics)" % " ".join(key), "count": len(rs),
                        "minutes": round(sum(x["minutes"] for x in rs), 1), "role": max(roles, key=roles.get),
                        "days": days})
    out.sort(key=lambda c: (-c["count"], -c["minutes"]))
    return out[:8]


# ---------------------------------------------------------------- daily

def daily(rows, day):
    """rows: normalized rows for at least `day` (more days give the streak). Returns a dict."""
    rows = dedupe(rows)
    today = [r for r in rows if r["date"] == day]
    work = [r for r in today if is_work(r)]
    roles = role_minutes(today)
    inferred_min = sum(r["minutes"] for r in today if r["source"] == "inferred")
    dist = distraction_by_day(rows)
    st, broke = streak(dist, day)
    nb, ni = blank_blocks(today)
    return {
        "day": day, "actions": len(work), "work_minutes": round(sum(r["minutes"] for r in work if r["source"] == "log"), 1),
        "inferred_minutes": round(inferred_min, 1), "roles": sorted(((k, round(v, 1)) for k, v in roles.items()),
                                                                    key=lambda kv: -kv[1]),
        "selling_minutes": round(roles.get("Sales", 0.0), 1), "distraction_minutes": round(dist.get(day, 0.0), 1),
        "streak": st, "streak_capped": not broke and st > 0, "blank_blocks": nb, "inferred_blocks": ni,
        "ai_minutes": round(sum(r["minutes"] for r in work if r["ai"]), 1),
        "sinks": time_sinks(today, 3), "breaks": round(sum(r["minutes"] for r in today if r["type"] == "break"), 1),
    }


def daily_line(d, written=None):
    day = C.md_label(C.parse_day(d["day"]))
    if not d["actions"] and not d["blank_blocks"]:
        return "Time Ledger %s: nothing logged today." % day
    top = ", ".join("%s %s" % (k, C.hours(v)) for k, v in d["roles"][:3])
    parts = ["%d actions, about %s of work" % (d["actions"], C.hours(d["work_minutes"]))]
    if top:
        parts.append(top)
    parts.append("selling %s" % C.hours(d["selling_minutes"]))
    parts.append("distraction %s (%s)" % (C.hours(d["distraction_minutes"]), "%d%s day(s) under 20 min in a row" % (
        d["streak"], "+" if d.get("streak_capped") else "")))
    if d["blank_blocks"]:
        parts.append("%d blank block(s), %d filled from your calendar or email" % (d["blank_blocks"],
                                                                                   d["inferred_blocks"]))
    if written is not None:
        parts.append("%s new row(s) in the Action Log" % written)
    return "Time Ledger %s: %s." % (day, "; ".join(parts))


def daily_markdown(d):
    lines = ["**%s**" % daily_line(d), ""]
    if d["roles"]:
        lines.append("Time by role (estimates):")
        lines += ["- %s: %s" % (k, C.hours(v)) for k, v in d["roles"]]
    if d["sinks"]:
        lines += ["", "Where the time went:"]
        lines += ["- %s: %s (%d action%s)" % (s["label"], C.hours(s["minutes"]), s["count"],
                                              "" if s["count"] == 1 else "s") for s in d["sinks"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- weekly

def week_bounds(day):
    """Monday..Sunday of the week holding `day` (a date)."""
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def weekly(this_rows, prev_rows, week_start, week_end, prev_roles=None, history=None):
    """this_rows/prev_rows: normalized rows. prev_roles: optional {role: minutes} already summed (SQL B).
    history: optional {date: distraction minutes} for days before this week (for the streak)."""
    rows = dedupe(this_rows)
    ws, we = week_start.isoformat(), week_end.isoformat()
    rows = [r for r in rows if ws <= r["date"] <= we]
    prev = dedupe(prev_rows or [])
    roles = role_minutes(rows)
    proles = prev_roles if prev_roles is not None else role_minutes(prev)
    all_roles = sorted(set(roles) | set(proles), key=lambda k: -(roles.get(k, 0) + 0.001 * proles.get(k, 0)))
    work = [r for r in rows if is_work(r) and r["source"] == "log"]
    total = sum(r["minutes"] for r in work)
    ptotal = sum(proles.values())
    dist = dict(history or {})
    dist.update(distraction_by_day(prev))
    dist.update(distraction_by_day(rows))
    days = [(week_start + dt.timedelta(days=i)).isoformat() for i in range(7)]
    logged_days = sorted({r["date"] for r in rows if r["type"] in ("action", "break")})
    st, broke = streak(dist, we)
    nb, ni = blank_blocks(rows)
    return {
        "week_start": ws, "week_end": we, "days_logged": len(logged_days),
        "days_missing": [d for d in days if d not in logged_days],
        "work_minutes": round(total, 1), "prev_work_minutes": round(ptotal, 1),
        "inferred_minutes": round(sum(r["minutes"] for r in rows if r["source"] == "inferred"), 1),
        "roles": [{"role": k, "minutes": round(roles.get(k, 0.0), 1), "prev": round(proles.get(k, 0.0), 1)}
                  for k in all_roles],
        "selling_minutes": round(roles.get("Sales", 0.0), 1), "prev_selling_minutes": round(proles.get("Sales", 0.0), 1),
        "distraction_minutes": round(sum(v for d, v in dist.items() if ws <= d <= we), 1),
        "distraction_by_day": [(d, round(dist[d], 1)) for d in days if d in dist],
        "streak": st, "streak_capped": not broke,
        "ai_minutes": round(sum(r["minutes"] for r in work if r["ai"]), 1),
        "sinks": time_sinks(rows, 5), "candidates": automation_candidates(rows),
        "blank_blocks": nb, "inferred_blocks": ni,
    }


def _delta(now, before):
    d = now - before
    if abs(d) < 5:
        return "about the same"
    return "%s %s" % ("up" if d > 0 else "down", C.hours(abs(d)))


def _title(w):
    a, b = C.parse_day(w["week_start"]), C.parse_day(w["week_end"])
    return "Time Ledger: week of %s to %s" % (C.md_label(a), C.md_label(b))


def weekly_lines(w):
    """Plain sentences, shared by every format. Returns list of (section, [lines])."""
    out = []
    top = ["You logged %d of 7 days and about %s of work (the week before: %s)." % (
        w["days_logged"], C.hours(w["work_minutes"]), C.hours(w["prev_work_minutes"]))]
    share = (100.0 * w["selling_minutes"] / w["work_minutes"]) if w["work_minutes"] else 0
    top.append("Selling time: %s, %d%% of your work (%s from the week before)." % (
        C.hours(w["selling_minutes"]), round(share), _delta(w["selling_minutes"], w["prev_selling_minutes"])))
    streak_txt = ("%d day(s) in a row under 20 minutes" % w["streak"]) + (" (as far back as the log goes)" if
                                                                          w["streak_capped"] and w["streak"] else "")
    top.append("Distraction: %s this week. Streak: %s." % (C.hours(w["distraction_minutes"]), streak_txt))
    if w["ai_minutes"]:
        top.append("Time on Claude and other AI tools: %s." % C.hours(w["ai_minutes"]))
    if w["blank_blocks"]:
        top.append("Blank blocks: %d. %d were filled in from your calendar, calls or email (marked inferred)." % (
            w["blank_blocks"], w["inferred_blocks"]))
    else:
        top.append("Blank blocks: none.")
    if w["days_missing"]:
        names = ", ".join(C.parse_day(d).strftime("%a") for d in w["days_missing"])
        top.append("Days with no log: %s." % names)
    out.append(("This week", top))
    out.append(("Time by role vs the week before",
                ["%s: %s (%s)" % (x["role"], C.hours(x["minutes"]), _delta(x["minutes"], x["prev"]))
                 for x in w["roles"]] or ["No work logged."]))
    out.append(("Top 5 time sinks",
                ["%s: %s over %d action%s. Biggest: \"%s\"" % (s["label"], C.hours(s["minutes"]), s["count"],
                                                              "" if s["count"] == 1 else "s", _short(s["example"]))
                 for s in w["sinks"]] or ["Nothing logged."]))
    out.append(("Done 3 or more times on 2 or more days (automation candidates)",
                ["\"%s\": %d times on %d day(s), %s in all (%s)" % (_short(c["label"], 60), c["count"], c["days"],
                                                                    C.hours(c["minutes"]), c["role"])
                 for c in w["candidates"]] or ["No action came up 3 or more times on 2 or more days."]))
    out.append(("Distraction by day",
                ["%s: %s%s" % (_dayname(d), C.hours(v), "" if v < DISTRACTION_LIMIT else
                               " (over 20)") for d, v in w["distraction_by_day"]] or ["No days logged."]))
    out.append(("What to do with this", next_steps(w)))
    return out


def next_steps(w):
    tips = []
    if w["candidates"]:
        c = w["candidates"][0]
        tips.append("Pick one repeat to hand off: \"%s\" came up %d times. Ask Claude to automate it." % (
            _short(c["label"], 50), c["count"]))
    if w["work_minutes"] and w["selling_minutes"] < 0.25 * w["work_minutes"]:
        tips.append("Selling was under a quarter of your work. Block the first hour of each day for calls.")
    if w["distraction_minutes"] >= 140:
        tips.append("Distraction averaged %s a day. Keep the phone out of the room for your first block." %
                    C.hours(w["distraction_minutes"] / 7.0))
    if w["blank_blocks"]:
        tips.append("Fill in blank blocks the same day, even with one word, so the numbers stay true.")
    tips.append("All minutes are estimates from your block times. Fix any row in the Action Log and next week's "
                "report uses your fix.")
    return tips


def weekly_markdown(w):
    lines = []
    for sec, items in weekly_lines(w):
        lines += ["## " + sec, ""]
        lines += ["- " + x for x in items]
        lines.append("")
    return "\n".join(lines)


def weekly_text(w):
    lines = [_title(w), ""]
    for sec, items in weekly_lines(w):
        lines += [sec.upper(), ""] + ["- " + x for x in items] + [""]
    return "\n".join(lines)


def _css():
    p = PALETTE
    return ("body{margin:0;background:%s;color:%s;font:16px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif}"
            ".wrap{max-width:640px;margin:0 auto;padding:16px}"
            ".card{background:%s;border:1px solid %s;border-radius:10px;padding:14px 16px;margin:12px 0}"
            "h1{font-size:20px;margin:4px 0 2px;color:%s}h2{font-size:16px;margin:0 0 8px;color:%s}"
            "ul{margin:0;padding-left:20px}li{margin:4px 0}.muted{color:#6b6f66;font-size:13px}"
            "@media (prefers-color-scheme: dark){body{background:%s;color:%s}.card{background:#22261f;"
            "border-color:#3a3f36}h1,h2{color:#a9c19a}.muted{color:#a8a89c}}"
            % (p["cream"], p["ink"], p["paper"], p["hair"], p["sage"], p["sage"], p["ink"], p["cream"]))


def weekly_html(w, updated=""):
    parts = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
             "<title>Time Ledger</title><style>%s</style></head><body><div class=\"wrap\">" % _css(),
             "<h1>%s</h1>" % html.escape(_title(w))]
    if updated:
        parts.append("<p class=\"muted\">Last updated %s. All minutes are estimates.</p>" % html.escape(updated))
    for sec, items in weekly_lines(w):
        parts.append("<div class=\"card\"><h2>%s</h2><ul>%s</ul></div>" % (
            html.escape(sec), "".join("<li>%s</li>" % html.escape(x) for x in items)))
    parts.append("</div></body></html>")
    return "".join(parts)


def daily_html(d, updated=""):
    items = ["<li>%s: %s</li>" % (html.escape(k), C.hours(v)) for k, v in d["roles"]]
    sinks = ["<li>%s: %s</li>" % (html.escape(s["label"]), C.hours(s["minutes"])) for s in d["sinks"]]
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width,initial-scale=1\"><title>Time Ledger</title><style>%s</style></head><body>"
            "<div class=\"wrap\"><h1>Time Ledger %s</h1>%s<div class=\"card\"><p>%s</p></div>"
            "<div class=\"card\"><h2>Time by role</h2><ul>%s</ul></div><div class=\"card\"><h2>Where the time went"
            "</h2><ul>%s</ul></div></div></body></html>") % (
        _css(), html.escape(C.md_label(C.parse_day(d["day"]))),
        ("<p class=\"muted\">Last updated %s. All minutes are estimates.</p>" % html.escape(updated)) if updated else "",
        html.escape(daily_line(d)), "".join(items) or "<li>Nothing logged.</li>",
        "".join(sinks) or "<li>Nothing logged.</li>")


def weekly_title(w):
    return _title(w)
