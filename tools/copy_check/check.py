"""Surven Copy Checker: checks a draft against Joey's locked copy rules (tools/copy_check/rules.json).

Library:
    from tools.copy_check.check import check
    result = check(text, "prospect_sms", require_link=False, require_optout=False)
    # {"ok": bool, "grade": float|None, "context": str, "counts": {...},
    #  "issues": [{"rule", "severity", "match", "line", "col", "message", "fix", "start", "end"}]}

CLI (run from the repo root):
    python3 -m tools.copy_check.check --context <prospect_email|prospect_sms|client|internal> \
        (--file <path> | --text "...") [--json] [--require-link] [--require-optout] [--template]
    --file - reads stdin. Exit 0 = no blocking issues, 1 = at least one, 2 = bad arguments or a checker error
    (so exit 1 always means "fix the copy", never "the checker broke").

`ok` is False when any issue has severity "block". Warnings are shown to Joey next to the draft.
`line` is 1-based; 0 means the issue is about the whole text (reading grade, length, missing link).
`start`/`end` are character offsets into the normalized text (None for whole-text issues).

The Copy Checker page (page_template.html) runs the SAME checks in JavaScript. The algorithms below
(normalize, sentence split, syllables, metrics) are mirrored there line for line, and
tests/test_parity.py proves both give the same answers. Change both together.
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "rules.json")
CONTEXTS = ("prospect_email", "prospect_sms", "client", "internal")
ALIASES = {
    "cold_email": "prospect_email", "email": "prospect_email", "prospect-email": "prospect_email",
    "cold_text": "prospect_sms", "cold_sms": "prospect_sms", "sms": "prospect_sms", "text": "prospect_sms",
    "prospect-sms": "prospect_sms", "clients": "client", "client_facing": "client",
}
KINDS = ("regex", "wordlist", "metric")
SEVERITIES = ("block", "warn")
METRICS = ("emoji", "lowercase_start", "sentence_words", "reading_grade", "question_marks", "question_words",
           "char_count", "non_gsm", "require_link", "require_optout")

# Abbreviations whose period does not end a sentence. Mirrored in the page's JS.
ABBREV = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "vs", "etc", "e.g", "i.e", "a.m", "p.m", "inc", "ltd",
          "co", "approx", "dept", "est", "u.s", "ave", "blvd", "mt", "ft", "sq", "jan", "feb", "apr", "jun",
          "jul", "aug", "sep", "sept", "oct", "nov", "dec", "mon", "tue", "tues", "thu", "thur", "thurs", "fri"}
# These can also end a sentence: "Call me at 3 p.m. Does that work?" splits when the next word is Capitalized.
ABBREV_END = {"a.m", "p.m", "etc", "inc", "ltd", "co"}

_WS = " \t\n\r\f\v"
_RE_ESC = set(".^$*+?()[]{}|\\/")
_BULLET = re.compile(r"[ \t]*(?:[-*\u2022]|\d{1,3}[.)])[ \t]+", re.A)
_TERM = re.compile(r"[.!?]+[\"')\]*_`]*(?![^\s])", re.A)
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*", re.A)
# Links, email addresses and bare domains (start.surven.ai/booking-page). Mirrored in the page's JS.
# Every repeat is bounded so odd input ("a.a.a.a..." pasted 10,000 times) stays linear time.
_LINKS = re.compile(r"https?://\S+|www\.\S+|[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}"
                    r"|\b[A-Za-z0-9][\w-]{0,62}(?:\.[\w-]{1,63}){0,4}\.(?:com|net|org|ai|io|co|us|info|biz|app)\b"
                    r"(?:[/?#]\S*)?", re.A | re.I)
_ALPHA = re.compile(r"[A-Za-z]")


# ---------------------------------------------------------------- rules

def load_rules(path=None):
    with open(path or RULES_PATH, encoding="utf-8") as f:
        return json.load(f)


def word_regex(word):
    """One wordlist entry -> regex source. Space or hyphen matches either; trailing * = any ending."""
    if word.startswith("re:"):
        return word[3:]
    wild = word.endswith("*")
    w = word[:-1] if wild else word
    out = []
    for ch in w:
        if ch in " -":
            if not out or out[-1] != "[\\s-]+":
                out.append("[\\s-]+")
        elif ch in _RE_ESC:
            out.append("\\" + ch)
        else:
            out.append(ch)
    body = "".join(out) + ("\\w*" if wild else "")
    pre = "\\b" if re.match(r"\w", w[0], re.A) else ""
    post = "\\b" if (wild or re.match(r"\w", w[-1], re.A)) else ""
    return pre + body + post


def compile_rules(raw):
    """rules.json -> the compiled, JSON-able form both checkers run (regex sources precomputed here)."""
    out = {k: v for k, v in raw.items() if k != "rules"}
    rules = []
    for r in raw["rules"]:
        c = dict(r)
        if r["kind"] == "regex":
            pats = r.get("patterns") or [{"pattern": r["pattern"], "flags": r.get("flags", "i")}]
            c["_res"] = [{"re": p["pattern"], "flags": p.get("flags", "i")} for p in pats]
        elif r["kind"] == "wordlist":
            entries = []
            for w in r["words"]:
                word, use = (w["w"], w.get("use")) if isinstance(w, dict) else (w, None)
                entries.append({"re": word_regex(word), "use": use, "n": len(word)})
            order = sorted(range(len(entries)), key=lambda i: -entries[i]["n"])
            c["_res"] = [{"re": "(?:" + "|".join(entries[i]["re"] for i in order) + ")",
                          "flags": r.get("flags", "i")}]
            c["_entries"] = [{"re": e["re"], "use": e["use"]} for e in entries]
        if "allow" in r:
            c["_allow"] = [a.lower() for a in r["allow"]]
        rules.append(c)
    out["rules"] = rules
    return out


_COMPILED = {}
_RX = {}


def compiled(path=None):
    key = path or RULES_PATH
    if key not in _COMPILED:
        _COMPILED[key] = compile_rules(load_rules(key))
    return _COMPILED[key]


def rx(source, flags="i"):
    k = (source, flags)
    if k not in _RX:
        f = re.A
        if "i" in flags:
            f |= re.I
        _RX[k] = re.compile(source, f)
    return _RX[k]


def resolve_context(context):
    c = (context or "").strip().lower()
    c = ALIASES.get(c, c)
    if c not in CONTEXTS:
        raise ValueError("unknown context %r, use one of: %s" % (context, ", ".join(CONTEXTS)))
    return c


# ---------------------------------------------------------------- text helpers (mirrored in JS)

def normalize(text):
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", t)
    t = re.sub("[\u2028\u2029]", "\n", t)
    return t.replace("\ufeff", "")


def straighten(text):
    """Same length as text: curly quotes become straight so patterns only need ' and "."""
    return (text.replace("\u2018", "'").replace("\u2019", "'").replace("\u02bc", "'")
            .replace("\u201c", '"').replace("\u201d", '"'))


def _is_ws(ch):
    return ch in _WS


def _rstrip(s):
    i = len(s)
    while i > 0 and _is_ws(s[i - 1]):
        i -= 1
    return s[:i]


def _alnum(ch):
    return bool(ch) and ("a" <= ch <= "z" or "A" <= ch <= "Z" or "0" <= ch <= "9")


def split_sentences(text):
    """(start, end) spans of sentences in text. A blank line, a bullet, or a line break after
    punctuation starts a new block; a line that ends in a letter and continues in lowercase is a soft
    wrap. Inside a block, . ! ? end a sentence unless it is an ellipsis or a known abbreviation."""
    blocks, cur, pos = [], None, 0
    for line in text.split("\n"):
        ls, le = pos, pos + len(line)
        pos = le + 1
        if not line.strip(_WS):
            cur = None
            continue
        m = _BULLET.match(line)
        if m:
            cur = [ls + m.end(), le]
            blocks.append(cur)
            continue
        start = ls + (len(line) - len(line.lstrip(_WS)))
        if cur is not None:
            prev = _rstrip(text[cur[0]:cur[1]])
            if prev and _alnum(prev[-1]) and "a" <= text[start] <= "z":
                cur[1] = le
                continue
        cur = [start, le]
        blocks.append(cur)

    spans = []
    for bs, be in blocks:
        seg = text[bs:be]
        s0 = 0
        for m in _TERM.finditer(seg):
            punct = m.group(0).rstrip("\"')]*_`")
            if len(punct) >= 2 and set(punct) == {"."}:
                continue
            if punct == ".":
                tok = re.split(r"\s", seg[:m.start()], flags=re.A)[-1].lstrip("([\"'")
                if tok.lower() in ABBREV or re.fullmatch(r"[A-Z]", tok):
                    if not (tok.lower() in ABBREV_END and _next_is_upper(seg, m.end())):
                        continue
            _add_span(spans, text, bs + s0, bs + m.end())
            s0 = m.end()
        _add_span(spans, text, bs + s0, be)
    return spans


def _next_is_upper(seg, i):
    while i < len(seg) and _is_ws(seg[i]):
        i += 1
    return i < len(seg) and "A" <= seg[i] <= "Z"


def blank_links(text):
    """Same length as text, with links, email addresses and bare domains turned into spaces."""
    return _LINKS.sub(lambda m: " " * len(m.group(0)), text)


def _add_span(spans, text, s, e):
    while s < e and _is_ws(text[s]):
        s += 1
    while e > s and _is_ws(text[e - 1]):
        e -= 1
    if e > s:
        spans.append((s, e))


def sentence_words(s):
    return [t for t in re.split(r"[ \t\n\r\f\v]+", s) if re.search(r"[A-Za-z0-9]", t)]


def count_words(s):
    """Words in a sentence, where a run of Capitalized words after the first word counts as one
    (so 'Oak Hill Senior Living' is one word, like 'it')."""
    n, prev_cap = 0, False
    for k, t in enumerate(sentence_words(s)):
        core = t.lstrip("\"'([")
        cap = k > 0 and core[:1] != "" and "A" <= core[0] <= "Z"
        if not (cap and prev_cap):
            n += 1
        prev_cap = cap and not t.rstrip("\"')]")[-1:] in (",", ".", ";", ":", "!", "?")
    return n


def is_proper(text, s, e):
    """A Capitalized (not ALL CAPS) match in the middle of a sentence: most likely part of a name.
    The first word of a line (after any bullet, number or quote) and the first word after . ! ? is not."""
    m = text[s:e]
    if not m or not ("A" <= m[0] <= "Z") or not re.search(r"[a-z]", m):
        return False
    ls = text.rfind("\n", 0, s) + 1
    if not _ALPHA.search(text, ls, s):
        return False
    i = s - 1
    while i >= 0 and text[i] in " \t\"'([":
        i -= 1
    return text[i] not in ".!?"


def syllables(word):
    w = word.lower().replace("'", "")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def reading_grade(plain, spans=None):
    """Flesch-Kincaid grade, rounded to 1 decimal and floored at 0. None if there are no words.
    Links and email addresses are blanked out first (same length), since they are not words to read."""
    spans = split_sentences(plain) if spans is None else spans
    text = blank_links(plain)
    words = _WORD.findall(text)
    if not words:
        return None, 0
    sents = sum(1 for s, e in spans if _WORD.search(text[s:e]))
    sents = max(sents, 1)
    syl = sum(syllables(w) for w in words)
    g = 0.39 * (len(words) / sents) + 11.8 * (syl / len(words)) - 15.59
    g = math.floor(g * 10 + 0.5) / 10
    return (g if g > 0 else 0.0), len(words)


# ---------------------------------------------------------------- the check

def _regex_hits(rule, text, template):
    hits = []
    for p in rule["_res"]:
        for m in rx(p["re"], p["flags"]).finditer(text):
            if m.end() > m.start():
                hits.append((m.start(), m.end()))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    kept, max_end = [], -1
    for h in hits:              # sorted by start, so h sits inside an earlier hit exactly when h ends by max_end
        if h[1] <= max_end:
            continue
        kept.append(h)
        max_end = h[1]
    if template and rule.get("template_ok"):
        ok_spans = [(m.start(), m.end()) for m in rx(rule["template_ok"], "i").finditer(text)]
        kept = [h for h in kept if not any(o[0] <= h[0] and h[1] <= o[1] for o in ok_spans)]
    for sk in rule.get("skip_if") or []:
        kept = [h for h in kept if not rx(sk["pattern"], sk.get("flags", "i")).fullmatch(text[h[0]:h[1]])]
    if rule.get("skip_proper"):
        kept = [h for h in kept if not is_proper(text, h[0], h[1])]
    if rule.get("before"):
        b = rx(rule["before"], "")
        kept = [h for h in kept if h[0] == 0 or b.fullmatch(text[h[0] - 1])]
    return kept


def _fix_for(rule, matched):
    use = None
    if rule["kind"] == "wordlist":
        for e in rule["_entries"]:
            if e["use"] and rx("(?:" + e["re"] + ")", "i").fullmatch(matched):
                use = e["use"]
                break
    elif rule.get("suggest"):
        frm, to = rule["suggest"]
        use = rx(frm, "i").sub(re.sub(r"\$(\d)", r"\\\1", to), matched, count=1)
    if use and rule.get("fix_use"):
        return rule["fix_use"].replace("{use}", use)
    return rule["fix"]


def _metric_hits(rule, norm, plain, spans, grade, nwords, opts):
    """List of (start, end, match) with start None for whole-text issues."""
    m = rule["metric"]
    out = []
    if m == "emoji":
        ranges = [(int(a, 16), int(b, 16)) for a, b in rule["ranges"]]
        i, n = 0, len(norm)
        while i < n:
            if any(a <= ord(norm[i]) <= b for a, b in ranges):
                j = i
                while j < n and any(a <= ord(norm[j]) <= b for a, b in ranges):
                    j += 1
                out.append((i, j, norm[i:j]))
                i = j
            else:
                i += 1
    elif m == "lowercase_start":
        for s, e in spans:
            i = s
            while i < e and plain[i] in "\"'([":
                i += 1
            if i >= e or not ("a" <= plain[i] <= "z"):
                continue
            j = i
            while j < e and not _is_ws(plain[j]):
                j += 1
            tok = plain[i:j]
            if ("://" in tok or tok.startswith("www.") or "@" in tok
                    or re.match(r"[a-z0-9-]+\.[a-z]{2,}", tok, re.A) or re.search(r"[A-Z]", tok[1:])):
                continue
            out.append((i, j, norm[i:j]))
    elif m == "sentence_words":
        for s, e in spans:
            if count_words(plain[s:e]) > rule["max"]:
                out.append((s, e, norm[s:e]))
    elif m == "question_words":
        for s, e in spans:
            sent = plain[s:e]
            if sent.rstrip("\"')]").endswith("?") and count_words(sent.split(",")[-1]) > rule["max"]:
                out.append((s, e, norm[s:e]))
    elif m == "reading_grade":
        if grade is not None and nwords >= rule.get("min_words", 0) and grade > rule["max"]:
            out.append((None, None, "grade %s" % _fmt_grade(grade)))
    elif m == "question_marks":
        qs = [i for i, ch in enumerate(blank_links(plain)) if ch == "?"]   # a ? inside a link is not a question
        if len(qs) > rule["max"]:
            q = qs[rule["max"]]
            out.append((q, q + 1, "%d questions" % len(qs)))
    elif m == "char_count":
        n = len(norm.strip(_WS))
        if n > rule["max"]:
            out.append((None, None, "%d characters" % n))
    elif m == "non_gsm":
        allowed = set(rule["charset"])
        seen, first = [], None
        for i, ch in enumerate(norm):
            if ch not in allowed and ch != "\n":
                if first is None:
                    first = i
                if ch not in seen:
                    seen.append(ch)
        if seen:
            out.append((first, first + 1, " ".join(seen)))
    elif m in ("require_link", "require_optout"):
        if opts.get(rule.get("flag", m)) and not rx(rule["pattern"], "i").search(plain):
            out.append((None, None, ""))
    return out


def _fmt_grade(g):
    return ("%.1f" % g)


def check(text, context, require_link=False, require_optout=False, template=False, rules=None):
    """Check one draft. Returns {"ok", "grade", "context", "counts", "issues"} (see module doc)."""
    ctx = resolve_context(context)
    comp = rules if rules is not None else compiled()
    norm = normalize(text or "")
    plain = straighten(norm)
    spans = split_sentences(plain)
    grade, nwords = reading_grade(plain, spans)
    opts = {"require_link": bool(require_link), "require_optout": bool(require_optout)}

    issues = []
    for idx, rule in enumerate(comp["rules"]):
        if ctx not in rule["contexts"]:
            continue
        sev = (rule.get("severity_by_context") or {}).get(ctx, rule["severity"])
        if rule["kind"] in ("regex", "wordlist"):
            src = norm if rule.get("on") == "raw" else plain
            allow = rule.get("_allow") or []
            for s, e in _regex_hits(rule, src, template):
                matched = norm[s:e]
                if matched.strip(_WS).lower() in allow:
                    continue
                issues.append(_issue(rule, idx, sev, s, e, matched, norm, _fix_for(rule, plain[s:e])))
        else:
            for s, e, matched in _metric_hits(rule, norm, plain, spans, grade, nwords, opts):
                issues.append(_issue(rule, idx, sev, s, e, matched, norm, rule["fix"]))

    fired = {i["rule"] for i in issues}
    drop = {r["id"] for r in comp["rules"] if r.get("suppressed_by") in fired}
    issues = [i for i in issues if i["rule"] not in drop]
    issues.sort(key=lambda i: (1 if i["start"] is None else 0, i["start"] or 0, i["_idx"]))
    for i in issues:
        del i["_idx"]
    nblock = sum(1 for i in issues if i["severity"] == "block")
    return {"ok": nblock == 0, "grade": grade, "context": ctx,
            "counts": {"block": nblock, "warn": len(issues) - nblock}, "issues": issues}


def _issue(rule, idx, sev, s, e, matched, norm, fix):
    if s is None:
        line, col = 0, 0
    else:
        line = norm.count("\n", 0, s) + 1
        col = s - (norm.rfind("\n", 0, s) + 1) + 1
    return {"rule": rule["id"], "severity": sev, "match": matched, "line": line, "col": col,
            "message": rule["message"], "fix": fix, "start": s, "end": e, "_idx": idx}


# ---------------------------------------------------------------- CLI

LABELS = {"prospect_email": "cold email", "prospect_sms": "cold text", "client": "client", "internal": "internal"}


def _short(s, n=70):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 3] + "..."


def human(result):
    c = result["counts"]
    head = "Copy check: %s" % ("PASS" if result["ok"] else "FIX FIRST")
    head += " (%d must fix, %d to look at)" % (c["block"], c["warn"])
    head += ", context %s" % LABELS[result["context"]]
    if result["grade"] is not None:
        head += ", reading grade %s" % _fmt_grade(result["grade"])
    lines = [head]
    for sev, title in (("block", "MUST FIX"), ("warn", "LOOK AT")):
        group = [i for i in result["issues"] if i["severity"] == sev]
        if not group:
            continue
        lines.append("")
        lines.append(title)
        for i in group:
            where = "line %d" % i["line"] if i["line"] else "whole text"
            what = ' "%s"' % _short(i["match"]) if i["match"] else ""
            lines.append("  %s [%s]%s" % (where, i["rule"], what))
            lines.append("    %s Fix: %s" % (i["message"], i["fix"]))
    return "\n".join(lines)


def decode(data):
    """Bytes from a file or stdin -> text. UTF-8 (with or without a BOM) first. A Windows-1252 file (Word, Outlook)
    falls back to cp1252 so its curly quotes and dashes stay visible to the checker instead of vanishing."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def main(argv=None):
    """Exit 0 = no blocking issues, 1 = at least one, 2 = bad arguments or the checker itself failed."""
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  a crash must never read as "has blocking issues" (exit 1)
        sys.stderr.write("copy_check error: %s: %s\n" % (type(e).__name__, e))
        return 2


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tools.copy_check.check",
                                 description="Check copy against Joey's locked copy rules.")
    ap.add_argument("--context", required=True, help="prospect_email | prospect_sms | client | internal")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="path to the draft, or - for stdin")
    src.add_argument("--text", help="the draft itself")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the plain report")
    ap.add_argument("--require-link", action="store_true", help="block if no booking link is present")
    ap.add_argument("--require-optout", action="store_true", help="block if no STOP / opt-out line (first texts)")
    ap.add_argument("--template", action="store_true",
                    help="allow GHL merge fields like {{contact.first_name}} (for templates, not final drafts)")
    ap.add_argument("--rules", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        ctx = resolve_context(a.context)
    except ValueError as e:
        ap.error(str(e))
    if a.text is not None:
        text = a.text
    elif a.file == "-":
        text = decode(sys.stdin.buffer.read())
    else:
        try:
            with open(a.file, "rb") as f:
                text = decode(f.read())
        except OSError as e:
            ap.error("cannot read %s: %s" % (a.file, e.strerror))
    rules = compile_rules(load_rules(a.rules)) if a.rules else None
    result = check(text, ctx, a.require_link, a.require_optout, a.template, rules=rules)
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
