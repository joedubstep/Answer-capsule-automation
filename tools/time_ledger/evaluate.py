"""Compare the Time Ledger's parse + labels + minutes with a hand-labeled history, for days both cover.

  python3 -m tools.time_ledger.evaluate --page <fetched page> --csv <labeled actions.csv> [--edited ISO]

Read-only. Prints aggregates only (counts, agreement rates, minutes by role); never prints action text, so the
output is safe to paste. Rows are matched inside a day by word overlap (with a small preference for the same
block time), one to one.
"""
import argparse
import csv
import re
import sys

from tools.time_ledger import classify as K
from tools.time_ledger import common as C
from tools.time_ledger import minutes as M
from tools.time_ledger import parse as P

MIN_SIM = 0.25


def _clock(s):
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AP]M)", s or "", re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3).upper()
    return h * 60 + mi + (720 if ap == "PM" else 0)


def _jac(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def match_day(mine, theirs):
    pairs = []
    for i, r in enumerate(mine):
        si = set(C.tokens(r["action_text"]))
        for j, t in enumerate(theirs):
            sj = set(C.tokens(t["action"]))
            s = _jac(si, sj)
            if s < MIN_SIM:
                continue
            tc, rc = _clock(t.get("clock")), r.get("block_min")
            if tc is not None and rc is not None:
                d = min(abs((rc % 1440) - tc), 1440 - abs((rc % 1440) - tc))
                s += 0.15 if d <= 5 else (0.05 if d <= 60 else 0.0)
            pairs.append((s, i, j))
    pairs.sort(reverse=True)
    used_i, used_j, out = set(), set(), []
    for s, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        out.append((mine[i], theirs[j]))
    return out


def model_without(csv_rows, day, shipped):
    """Same settings as the shipped model, refit on every labeled day except `day` (an honest test)."""
    train = [t for t in csv_rows if K.usable(t) and t["day"] != day]
    texts = [t["action"] for t in train]
    banned = K.proper_stems(texts)
    m = {"targets": {}}
    for tgt in K.TARGETS:
        old = shipped["targets"][tgt]
        fm = K.fit(texts, [K.label_of(t, tgt) for t in train], banned, old["classes"])
        fm.update({k: old[k] for k in ("alpha", "lex_weight", "temperature", "threshold")})
        fm["_vs"] = set(fm["vocab"])
        m["targets"][tgt] = fm
    return m


def evaluate(page_raw, csv_rows, edited=None, holdout=False):
    res = P.parse_page(page_raw, edited)
    rows = M.estimate(res["rows"])
    shipped = K.load_model()
    ref_days = {}
    for t in csv_rows:
        ref_days.setdefault(t["day"], []).append(t)
    for r in rows:
        model = shipped
        if holdout and r["log_date"] in ref_days:
            key = "_m_" + r["log_date"]
            if key not in ref_days:
                ref_days[key] = model_without(csv_rows, r["log_date"], shipped)
            model = ref_days[key]
        K.label_row(r, model)
    ref_days = {k: v for k, v in ref_days.items() if not k.startswith("_m_")}
    out = {"days": [], "sections": res["sections"]}
    tot = {"matched": 0, "role": 0, "kind": 0, "ai": 0, "conf_n": 0, "conf_role": 0, "low_n": 0, "low_role": 0,
           "mine": 0, "theirs": 0}
    role_min_mine, role_min_ref = {}, {}
    for day in sorted(ref_days):
        mine = [r for r in rows if r["log_date"] == day and r["type"] == "action"]
        theirs = [t for t in ref_days[day] if K.usable(t)]
        if not mine:
            continue
        pairs = match_day(mine, theirs)
        rm = sum(1 for a, b in pairs if a["role"] == b["role"])
        out["days"].append({"day": day, "parsed_actions": len(mine), "labeled_actions": len(theirs),
                            "matched": len(pairs), "role_agree": rm,
                            "parsed_minutes": round(sum(r["minutes"] for r in mine), 1),
                            "labeled_minutes": round(sum(float(t["minutes"] or 0) for t in theirs), 1)})
        tot["mine"] += len(mine)
        tot["theirs"] += len(theirs)
        tot["matched"] += len(pairs)
        tot["role"] += rm
        tot["kind"] += sum(1 for a, b in pairs if a["kind"] == b["kind"])
        tot["ai"] += sum(1 for a, b in pairs if a["ai"] == (b["ai"] == "yes"))
        for a, b in pairs:
            if a["needs_label"]:
                tot["low_n"] += 1
                tot["low_role"] += a["role"] == b["role"]
            else:
                tot["conf_n"] += 1
                tot["conf_role"] += a["role"] == b["role"]
        for r in mine:
            role_min_mine[r["role"]] = role_min_mine.get(r["role"], 0.0) + r["minutes"]
        for t in theirs:
            role_min_ref[t["role"]] = role_min_ref.get(t["role"], 0.0) + float(t["minutes"] or 0)
    out["totals"] = tot
    out["role_minutes"] = sorted(((k, round(role_min_mine.get(k, 0.0)), round(role_min_ref.get(k, 0.0)))
                                  for k in set(role_min_mine) | set(role_min_ref)), key=lambda x: -x[2])
    return out


def _pct(a, b):
    return "%.0f%%" % (100.0 * a / b) if b else "n/a"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--page", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--edited")
    ap.add_argument("--holdout", action="store_true", help="label each day with a model that never saw that day")
    a = ap.parse_args(argv)
    with open(a.page, encoding="utf-8") as f:
        raw = f.read()
    with open(a.csv, encoding="utf-8") as f:
        ref = list(csv.DictReader(f))
    out = evaluate(raw, ref, a.edited, a.holdout)
    print("labels from: %s" % ("a model refit without each day (honest test)" if a.holdout else
                               "the shipped model (it was trained on these days)"))
    for s in out["sections"]:
        if s["suspect"]:
            print("date check: %-20s -> %s (%s)" % (s["heading"], s["resolved"], "; ".join(s["notes"])))
    print("%-10s %7s %7s %7s %10s %9s %9s" % ("day", "parsed", "labeled", "matched", "role agree", "min est",
                                             "min real"))
    for d in out["days"]:
        print("%-10s %7d %7d %7d %10s %9.0f %9.0f" % (d["day"], d["parsed_actions"], d["labeled_actions"],
                                                     d["matched"], _pct(d["role_agree"], d["matched"]),
                                                     d["parsed_minutes"], d["labeled_minutes"]))
    t = out["totals"]
    print("matched %d of %d parsed actions (%d labeled). role agreement %s, kind %s, ai %s" % (
        t["matched"], t["mine"], t["theirs"], _pct(t["role"], t["matched"]), _pct(t["kind"], t["matched"]),
        _pct(t["ai"], t["matched"])))
    print("confident rows: %d, role agreement %s; low-confidence rows (sent to Claude): %d, role agreement %s" % (
        t["conf_n"], _pct(t["conf_role"], t["conf_n"]), t["low_n"], _pct(t["low_role"], t["low_n"])))
    print("minutes by role (estimated vs labeled):")
    for k, mine, ref_m in out["role_minutes"]:
        print("  %-22s %5d %5d" % (k, mine, ref_m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
