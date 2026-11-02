"""Copy check for every piece of client-facing text (BUILD-SPEC rule 4).

  check(text, "client", template=True, blanks=("[N]",)) -> {"ok", "checker", "blocks", "warns", "grade"}

Uses tools/copy_check (the same rules as the Copy Checker page). `template=True` allows GoHighLevel merge fields like
{{contact.first_name}}. `blanks` are the marked gaps Joey fills by hand (like [N] rooms); they are not errors here,
the page counts them instead. If tools/copy_check is missing, a small built-in check runs and says so.
"""
import re

BASIC = [
    ("dash", re.compile("[\u2012-\u2015]"), "No em or en dashes."),
    ("care_home", re.compile(r"\bcare[\s-]+homes?\b", re.I), "Never 'care home' in client text."),
    ("leads_for_families", re.compile(r"\bleads?\b", re.I), "Say families, not leads."),
    ("patients", re.compile(r"\bpatients?\b", re.I), "Say residents, not patients."),
    ("enquiry", re.compile(r"\benquir", re.I), "US English: inquiry."),
]


def _slim(i):
    return {"rule": i.get("rule"), "match": (i.get("match") or "")[:60], "fix": i.get("fix") or i.get("message") or "",
            "line": i.get("line", 0)}


def check(text, context="client", template=False, blanks=()):
    text = text or ""
    try:
        from tools.copy_check.check import check as cc
    except Exception:  # noqa: BLE001  (missing or broken checker: fall back, never skip)
        cc = None
    if cc is None:
        blocks = []
        for rule, rx, fix in BASIC:
            for m in rx.finditer(text):
                blocks.append({"rule": rule, "match": m.group(0), "fix": fix, "line": text.count("\n", 0, m.start()) + 1})
        return {"ok": not blocks, "checker": "basic (tools/copy_check not found)", "blocks": blocks, "warns": [],
                "grade": None}
    r = cc(text, context, template=template)
    keep = set(b.strip() for b in blanks)
    issues = [i for i in r.get("issues") or [] if not (i.get("rule") == "merge_field" and (i.get("match") or "").strip() in keep)]
    blocks = [_slim(i) for i in issues if i.get("severity") == "block"]
    warns = [_slim(i) for i in issues if i.get("severity") != "block"]
    return {"ok": not blocks, "checker": "copy_check", "blocks": blocks, "warns": warns, "grade": r.get("grade")}


def summary(result):
    """One short line for the page and the console."""
    if not result:
        return ""
    if result["ok"] and not result["warns"]:
        return "Copy check: pass."
    if result["ok"]:
        return "Copy check: pass, %d to look at: %s." % (len(result["warns"]), "; ".join(
            "%s (%s)" % (w["rule"], w["match"]) if w["match"] else w["rule"] for w in result["warns"][:4]))
    return "Copy check: HELD, %d to fix: %s." % (len(result["blocks"]), "; ".join(
        "%s (%s)" % (b["rule"], b["match"]) for b in result["blocks"][:4]))
