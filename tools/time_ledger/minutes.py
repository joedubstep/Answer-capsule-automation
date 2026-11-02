"""Estimate minutes per action from the block start times. Every number here is an estimate.

Rules (per log day, blocks in time order):
- A block runs from its start to the next block's start (the gap), capped at CAP (30) minutes of work.
  When the actions name their own durations ("for 15 minutes", "until 12:04", "N1 done 11:31") and those add
  up to more than the cap, the named total is used instead (still no more than the gap).
- Blocks with no time ("Spent 10 minutes on a snack break") share the gap of the timed block above them.
- The last block of the day gets its named durations, or 15 minutes (one log interval).
- "Stopped working 9:15 ... back 10:10": the break runs 9:15 to 10:10 and the work after it runs to the next
  block. "stopping work" at the end of a block: the rest of the gap after the work is a break.
- Inside a block, actions with a named duration get it; the rest of the block is shared by a simple weight
  (longer descriptions get a little more), with at least half a minute each.
- A blank block keeps its window (start to start + its minutes) so the skill can look for what happened then.
"""
import re

from tools.time_ledger import common as C
from tools.time_ledger.parse import parse_clock_token, resolve_clock

CAP = 30.0
LAST_BLOCK = 15.0
MIN_SHARE = 0.5
LONG_GAP = 180.0     # a gap longer than this between entries is time off, not uncounted work

DUR = re.compile(r"(?<![\w-])(?:about\s+|like\s+|around\s+|roughly\s+|maybe\s+)?(\d{1,3}(?:\.\d+)?)\s*(?:-?\s*ish\s*)?"
                 r"(?:more\s+)?(min(?:ute)?s?|hours?|hrs?|seconds?|secs?)\b", re.I)
FOR_N = re.compile(r"\bfor\s+(?:like\s+|about\s+|around\s+)?(\d{1,3})\s*$", re.I)
UNTIL = re.compile(r"\buntil\s+(\d{1,2}:\d{2}\s*(?:[ap]\.?\s?m\b\.?)?)", re.I)
NOT_DURATION = re.compile(r"\b(?:a|per)\s+(?:week|day|month)\b|\bdown to\b|\bwithin\b|\bsaves?\b|\bfaster\b", re.I)


def named_minutes(text, block_min=None, done_min=None):
    """Duration the action text names itself, in minutes, or None."""
    if done_min is not None and block_min is not None and done_min > block_min:
        return float(done_min - block_min)
    if not text or NOT_DURATION.search(text):
        return None
    m = UNTIL.search(text)
    if m and block_min is not None:
        end = resolve_clock(parse_clock_token(m.group(1)), block_min)[0]
        if end is not None and 0 < end - block_min <= 300:
            return float(end - block_min)
    total = 0.0
    for n, unit in DUR.findall(text):
        v = float(n)
        u = unit.lower()
        if u.startswith("h"):
            v *= 60
        elif u.startswith("s"):
            v /= 60.0
        total += v
    if not total:
        m = FOR_N.search(text)
        if m:
            total = float(m.group(1))
    return min(total, 240.0) if total else None


def _weight(text):
    return 1.0 + min(len((text or "").split()), 24) ** 0.5 / 2.0


def _share(actions, budget):
    """actions: list of (row, named or None). Gives each row 'minutes'."""
    work = [(r, n) for r, n in actions]
    if not work:
        return
    named = sum(n for _, n in work if n)
    rest = [r for r, n in work if not n]
    if named > budget and named > 0:
        floor = MIN_SHARE * len(rest)
        scale = max(budget - floor, 0.0) / named if budget > floor else 0.0
        for r, n in work:
            r["minutes"] = round(n * scale, 1) if n else MIN_SHARE
        return
    left = budget - named
    wsum = sum(_weight(r["action_text"]) for r in rest)
    for r, n in work:
        if n:
            r["minutes"] = round(n, 1)
        else:
            r["minutes"] = round(max(MIN_SHARE, left * _weight(r["action_text"]) / wsum), 1) if wsum else MIN_SHARE


def estimate(rows, cap=CAP, last_block=LAST_BLOCK):
    """Adds minutes, minutes_est, window_start/window_end (minutes since the log day's midnight) to rows."""
    days = {}
    for r in rows:
        days.setdefault(r["log_date"], {}).setdefault(r["block_index"], []).append(r)
    for day, blocks in days.items():
        order = sorted(blocks)
        starts = {bi: blocks[bi][0]["block_min"] for bi in order}
        # segments: a timed block plus the untimed blocks under it
        segs, cur = [], None
        for bi in order:
            if starts[bi] is not None or cur is None:
                cur = [bi]
                segs.append(cur)
            else:
                cur.append(bi)
        for si, seg in enumerate(segs):
            start = starts[seg[0]]
            nxt = None
            for later in segs[si + 1:]:
                if starts[later[0]] is not None:
                    nxt = starts[later[0]]
                    break
            gap = (nxt - start) if (start is not None and nxt is not None and nxt > start) else None
            # per block: named durations and markers
            info = []
            for bi in seg:
                brs = sorted(blocks[bi], key=lambda r: r["position"])
                acts = [r for r in brs if r["type"] == "action"]
                named = {id(r): named_minutes(r["action_text"], r["block_min"], r.get("done_min")) for r in acts}
                demand = sum(v for v in named.values() if v) or None
                info.append((bi, brs, acts, named, demand))
            lead = blocks[seg[0]][0]
            work_start = start
            lead_break = 0.0
            if lead.get("lead_stop") and start is not None:
                if lead.get("resume_min") is not None and lead["resume_min"] > start:
                    lead_break = float(lead["resume_min"] - start)
                    work_start = lead["resume_min"]
                elif gap is not None:
                    lead_break = max(gap - cap, 0.0)
                    work_start = start + lead_break
            span = (nxt - work_start) if (work_start is not None and nxt is not None and nxt > work_start) else None
            n_blocks = len(info)
            named_total = sum(d or 0 for _, _, _, _, d in info)
            if span is None:
                budget = named_total if named_total else last_block * n_blocks
                budget = min(budget, max(cap, named_total)) if named_total else min(budget, cap * n_blocks)
            else:
                budget = min(span, cap * n_blocks)
                if named_total > budget:
                    budget = min(span, named_total)
            demands = [(d if d else last_block) for _, _, _, _, d in info]
            dsum = sum(demands) or 1.0
            has_stop = any(r["type"] == "break" and not (r is lead and lead.get("lead_stop"))
                           for _, brs, _, _, _ in info for r in brs)
            leftover = (span - budget) if span is not None else 0.0
            cursor = work_start
            for (bi, brs, acts, named, demand), dmd in zip(info, demands):
                b_budget = budget * dmd / dsum
                _share([(r, named[id(r)]) for r in acts], b_budget)
                for r in brs:
                    r["window_start"] = cursor
                    r["window_end"] = (cursor + b_budget) if cursor is not None else None
                    if r["type"] == "blank":
                        r["minutes"] = round(b_budget, 1)
                    elif r["type"] == "break":
                        if r is lead and lead.get("lead_stop") and r["position"] == 0:
                            r["minutes"] = round(lead_break, 1)
                        else:
                            r["minutes"] = round(leftover, 1) if leftover > 0 else 0.0
                            leftover = 0.0
                    r["minutes_est"] = True
                    r["gap_unlogged"] = 0.0
                    r["next_start"] = nxt
                if cursor is not None:
                    cursor += b_budget
            if leftover > 0 and not has_stop and span is not None and span <= LONG_GAP:
                last_rows = blocks[seg[-1]]
                for r in last_rows:
                    r["gap_unlogged"] = round(leftover / len(last_rows), 1)
    return rows


def day_totals(rows):
    """{date: {'work': minutes, 'breaks': minutes, 'blank': minutes, 'unlogged': minutes}}"""
    out = {}
    for r in rows:
        d = out.setdefault(r["log_date"], {"work": 0.0, "breaks": 0.0, "blank": 0.0, "unlogged": 0.0})
        m = r.get("minutes") or 0.0
        if r["type"] == "action":
            d["work"] += m
        elif r["type"] == "break":
            d["breaks"] += m
        else:
            d["blank"] += m
        d["unlogged"] += r.get("gap_unlogged") or 0.0
    return {k: {kk: round(vv, 1) for kk, vv in v.items()} for k, v in out.items()}
