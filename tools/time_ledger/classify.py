"""Label each 15-minute-log action with role, task, kind and AI, plus a confidence.

  python3 -m tools.time_ledger.classify train --csv <labeled actions.csv> [--names <extra stoplist>] [--out model.json]
  python3 -m tools.time_ledger.classify predict --text "send prompt to fix the agent"

The model is a multinomial naive Bayes over word unigrams and bigrams (binarized), plus a hand-made keyword
lexicon (lexicon.py). Training prints cross-validated accuracy and picks the confidence threshold below which a
row goes to the model (the skill) to label.

Privacy (this repo is public): training reads the labeled CSV from outside the repo and ships ONLY counts of
tokens that appear in 3 or more rows. Any token written with a capital letter mid-sentence in the history
(a possible person name) is dropped unless it is a known tool or generic word (lexicon.ALLOW_CAPITALIZED), and
so is anything in the optional --names stoplist (kept outside the repo). The CSV and the action texts are never
written into the repo.
"""
import argparse
import csv
import json
import math
import random
import re
import sys

from tools.time_ledger import common as C
from tools.time_ledger import lexicon as L

TARGETS = ("role", "kind", "task", "ai")
MIN_DF = 3
LEX = {"role": L.ROLE, "kind": L.KIND, "ai": L.AI, "task": {}}
_MODEL = None
# Rows below this role confidence go to Claude to label. Live log text is rawer than the cleaned training text:
# on 2026-11-02, labeling each logged day with a model that never saw it, 79% of rows at or above 0.75 were
# right versus 56% of all rows (and 72% at the cross-validated cut). So the live cut is the higher of the two.
ROUTE_THRESHOLD = 0.75
# Phone-scrolling words win over the statistics unless the action is clearly work on that app (a prompt about it).
DISTRACT = re.compile(r"\b(reels?|hinge|snapchat|spotlight|scroll(?:ing|ed)?|tiktok|instagram|distracted)\b", re.I)
WORKY = re.compile(r"\b(prompt|claude|transcri\w*|chat|post(?:ed|ing)?|ads?|campaign|client)\b", re.I)


# ---------------------------------------------------------------- features

def features(text):
    toks = C.tokens(text)
    feats = set(toks)
    feats.update(a + "_" + b for a, b in zip(toks, toks[1:]))
    return feats, toks


def _lex_compiled():
    out = {}
    for tgt, table in LEX.items():
        out[tgt] = {lab: [tuple(C.tokens(p, keep_stop=True)) for p in phrases] for lab, phrases in table.items()}
    return out


_LEXC = _lex_compiled()


def lex_hits(toks, target):
    """{label: number of lexicon phrases found} for one action."""
    out = {}
    raw = tuple(toks)
    for lab, phrases in _LEXC.get(target, {}).items():
        n = 0
        for ph in phrases:
            if not ph:
                continue
            k = len(ph)
            if any(raw[i:i + k] == ph for i in range(len(raw) - k + 1)):
                n += 1
        if n:
            out[lab] = n
    return out


# ---------------------------------------------------------------- privacy filter

def proper_stems(texts, extra_names=()):
    """Stems of words written with a capital letter mid-sentence (possible names), minus allowed words."""
    out = set()
    for t in texts:
        words = re.findall(r"[A-Za-z][A-Za-z0-9\-']*", C.clean(t))
        for i, w in enumerate(words):
            base = re.sub(r"'s$", "", w)
            if i > 0 and base[:1].isupper() and base.lower() not in L.ALLOW_CAPITALIZED:
                for piece in re.findall(r"[a-z][a-z0-9]*", base.lower()):
                    out.add(C.stem(piece))
    for n in extra_names:
        for piece in re.findall(r"[a-z][a-z0-9]*", n.lower()):
            out.add(C.stem(piece))
    return out


def allowed_feature(f, banned):
    return not any(part in banned for part in f.split("_"))


# ---------------------------------------------------------------- training

def label_of(row, target):
    if target == "ai":
        return "yes" if str(row.get("ai", "")).strip().lower() in ("yes", "true", "1") else "no"
    return (row.get(target) or "").strip()


def usable(row):
    return (row.get("role") or "").strip() not in ("", C.NOT_LOGGED) and (row.get("timing") or "") != "break"


def fit(texts, labels, banned, classes=None, min_df=MIN_DF):
    feats = [features(t)[0] for t in texts]
    df = {}
    for fs in feats:
        for f in fs:
            df[f] = df.get(f, 0) + 1
    vocab = sorted(f for f, n in df.items() if n >= min_df and allowed_feature(f, banned))
    vs = set(vocab)
    classes = list(classes or sorted(set(labels)))
    docs = {c: 0 for c in classes}
    counts = {c: {} for c in classes}
    totals = {c: 0 for c in classes}
    for fs, y in zip(feats, labels):
        if y not in docs:
            continue
        docs[y] += 1
        for f in fs:
            if f in vs:
                counts[y][f] = counts[y].get(f, 0) + 1
                totals[y] += 1
    return {"classes": classes, "docs": docs, "counts": counts, "totals": totals, "vocab": vocab}


def scores(m, feats, hits, alpha, lex_w):
    V = max(1, len(m["vocab"]))
    vs = set(m["vocab"]) if "_vs" not in m else m["_vs"]
    N = sum(m["docs"].values())
    K = len(m["classes"])
    seen = [c for c in m["classes"] if m["docs"][c]]
    avg_total = (sum(m["totals"][c] for c in seen) / len(seen)) if seen else 1.0
    out = {}
    for c in m["classes"]:
        s = math.log((m["docs"][c] + 1.0) / (N + K))
        tot = m["totals"][c] if m["docs"][c] else avg_total
        den = tot + alpha * V
        cc = m["counts"][c]
        for f in feats:
            if f in vs:
                s += math.log((cc.get(f, 0) + alpha) / den)
        s += lex_w * hits.get(c, 0)
        out[c] = s
    return out


def softmax(sc, temp):
    mx = max(sc.values())
    ex = {c: math.exp((v - mx) / temp) for c, v in sc.items()}
    z = sum(ex.values())
    return {c: v / z for c, v in ex.items()}


def _folds(n, k, seed=7):
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return [idx[i::k] for i in range(k)]


def cross_validate(texts, labels, target, banned, classes, alpha, lex_w, k=5):
    """Out-of-fold (score dict, true label) for every row."""
    out = [None] * len(texts)
    for fold in _folds(len(texts), k):
        test = set(fold)
        tr_t = [t for i, t in enumerate(texts) if i not in test]
        tr_y = [y for i, y in enumerate(labels) if i not in test]
        m = fit(tr_t, tr_y, banned, classes)
        m["_vs"] = set(m["vocab"])
        for i in fold:
            fs, toks = features(texts[i])
            out[i] = (scores(m, fs, lex_hits(toks, target), alpha, lex_w), labels[i])
    return out


def _acc(pairs):
    return sum(1 for sc, y in pairs if max(sc, key=sc.get) == y) / max(1, len(pairs))


def _logloss(pairs, temp):
    tot = 0.0
    for sc, y in pairs:
        p = softmax(sc, temp).get(y, 1e-9)
        tot -= math.log(max(p, 1e-9))
    return tot / max(1, len(pairs))


def pick_threshold(pairs, temp, target_acc=0.85):
    """Lowest confidence cut where the rows at or above it are right at least target_acc of the time."""
    conf = []
    for sc, y in pairs:
        p = softmax(sc, temp)
        top = max(p, key=p.get)
        conf.append((p[top], top == y))
    conf.sort(key=lambda x: -x[0])
    best, right = 1.0, 0
    for i, (c, ok) in enumerate(conf, 1):
        right += ok
        if right / i >= target_acc:
            best = c
    return round(best, 3)


def train(rows, extra_names=(), k=5, log=print):
    rows = [r for r in rows if usable(r)]
    texts = [r["action"] for r in rows]
    banned = proper_stems(texts, extra_names)
    model = {"version": 1, "trained_rows": len(rows), "min_df": MIN_DF, "targets": {}, "cv": {}}
    for tgt in TARGETS:
        labels = [label_of(r, tgt) for r in rows]
        if tgt == "role":
            classes = list(C.ROLES)
        elif tgt == "kind":
            classes = sorted(set(labels) | set(L.KIND))
        else:
            classes = sorted(set(labels))
        best = None
        for alpha in (0.3, 0.6, 1.0):
            for lw in ((0.0, 1.0, 2.0, 3.0) if LEX.get(tgt) else (0.0,)):
                pairs = cross_validate(texts, labels, tgt, banned, classes, alpha, lw, k)
                acc = _acc(pairs)
                if best is None or acc > best[0] + 1e-9:
                    best = (acc, alpha, lw, pairs)
        acc, alpha, lw, pairs = best
        temp = min((1.0, 1.5, 2.0, 3.0, 4.0, 6.0), key=lambda t: _logloss(pairs, t))
        thr = pick_threshold(pairs, temp)
        conf_ok = [(sc, y) for sc, y in pairs if max(softmax(sc, temp).values()) >= thr]
        base = max(labels.count(c) for c in set(labels)) / len(labels)
        m = fit(texts, labels, banned, classes)
        m.update({"alpha": alpha, "lex_weight": lw, "temperature": temp, "threshold": thr})
        model["targets"][tgt] = m
        model["cv"][tgt] = {"folds": k, "accuracy": round(acc, 3), "majority_baseline": round(base, 3),
                            "threshold": thr, "share_confident": round(len(conf_ok) / len(pairs), 3),
                            "accuracy_when_confident": round(_acc(conf_ok), 3) if conf_ok else None,
                            "alpha": alpha, "lex_weight": lw, "temperature": temp, "vocab": len(m["vocab"])}
        log("%-5s cv accuracy %.1f%% (baseline %.1f%%), confident %.0f%% of rows at >= %.2f -> %.1f%% right; "
            "vocab %d, alpha %s, lexicon %s, temp %s" % (
                tgt, 100 * acc, 100 * base, 100 * model["cv"][tgt]["share_confident"], thr,
                100 * (model["cv"][tgt]["accuracy_when_confident"] or 0), len(m["vocab"]), alpha, lw, temp))
    return model


def check_privacy(model, banned=()):
    """Every shipped feature must be allowed. Returns a list of problems (empty = fine)."""
    bad = []
    for tgt, m in model.get("targets", {}).items():
        for f in m["vocab"]:
            if not allowed_feature(f, banned):
                bad.append((tgt, f))
            if not re.fullmatch(r"[a-z0-9_]+", f):
                bad.append((tgt, f))
    return bad


# ---------------------------------------------------------------- predict

def load_model(path=None):
    global _MODEL
    if _MODEL is None or path:
        with open(path or C.MODEL_PATH, encoding="utf-8") as f:
            m = json.load(f)
        for t in m["targets"].values():
            t["_vs"] = set(t["vocab"])
        if path:
            return m
        _MODEL = m
    return _MODEL


def predict_text(text, model=None):
    model = model or load_model()
    fs, toks = features(text)
    out = {}
    for tgt in TARGETS:
        m = model["targets"][tgt]
        hits = lex_hits(toks, tgt)
        p = softmax(scores(m, fs, hits, m["alpha"], m["lex_weight"]), m["temperature"])
        top = max(p, key=p.get)
        out[tgt] = top
        out[tgt + "_conf"] = round(p[top], 3)
        if tgt == "role":
            ranked = sorted(p.items(), key=lambda kv: -kv[1])[:3]
            out["role_top3"] = [[c, round(v, 3)] for c, v in ranked]
    out["ai"] = out["ai"] == "yes"
    return out


def label_row(row, model=None):
    """Adds role, task, kind, ai, confidence and needs_label to one parsed row (in place) and returns it."""
    model = model or load_model()
    typ = row.get("type")
    if typ in ("blank", "break"):
        row.update({"role": C.NOT_LOGGED, "kind": C.NOT_LOGGED, "task": C.BREAK_TASK if typ == "break" else "",
                    "ai": False, "confidence": 1.0, "needs_label": False, "labeled_by": "rule"})
        return row
    text = row.get("action_text", "")
    p = predict_text(text, model)
    thr = max(model["targets"]["role"]["threshold"], ROUTE_THRESHOLD)
    row.update({"role": p["role"], "kind": p["kind"], "task": p["task"], "ai": p["ai"],
                "confidence": p["role_conf"], "role_top3": p["role_top3"],
                "needs_label": p["role_conf"] < thr, "labeled_by": "classifier"})
    if DISTRACT.search(text) and not WORKY.search(text):
        row.update({"role": "Personal", "kind": "Distraction", "task": "Distractions and personal", "ai": False,
                    "confidence": max(p["role_conf"], 0.9), "needs_label": False, "labeled_by": "rule"})
    return row


# ---------------------------------------------------------------- cli

def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--csv", required=True, help="labeled actions CSV (kept outside the repo)")
    t.add_argument("--names", help="optional extra stoplist, one word per line (kept outside the repo)")
    t.add_argument("--out", default=C.MODEL_PATH)
    t.add_argument("--folds", type=int, default=5)
    p = sub.add_parser("predict")
    p.add_argument("--text", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "train":
        names = []
        if a.names:
            with open(a.names, encoding="utf-8") as f:
                names = [x.strip() for x in f if x.strip()]
        rows = read_csv(a.csv)
        model = train(rows, names, a.folds)
        banned = proper_stems([r["action"] for r in rows if usable(r)], names)
        bad = check_privacy(model, banned)
        if bad:
            print("PRIVACY CHECK FAILED: %d features" % len(bad))
            return 2
        for m in model["targets"].values():
            m.pop("_vs", None)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(model, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
        print("model written: %s (%d rows, privacy check passed)" % (a.out, model["trained_rows"]))
        return 0
    print(json.dumps(predict_text(a.text), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
