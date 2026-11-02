"""Reply drafts: the template skeletons and the copy check every draft must pass.

  python3 -m tools.inbox_desk.drafts check --file /tmp/inbox_desk/drafts/<thread>.txt --context prospect_email [--require-link]
      Exit 0 = no blocking issue, 1 = fix it and check again. Prints one JSON line.

The skeletons are written by `python3 -m tools.inbox_desk.desk skeletons` from templates.md.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "templates.md")
MISSING_LINK = "[booking link]"


def parse_templates(path=TEMPLATES):
    """{key: text} from every '## key' section's first ```text block."""
    with open(path, encoding="utf-8") as f:
        md = f.read()
    out = {}
    for m in re.finditer(r"^## ([a-z_]+)\s*$(.*?)(?=^## |\Z)", md, re.M | re.S):
        block = re.search(r"```text\n(.*?)\n```", m.group(2), re.S)
        if block:
            out[m.group(1)] = block.group(1).strip() + "\n"
    return out


def greeting(first):
    return f"Hi {first}," if first else "Hi,"


def fill(template, item, booking_link):
    home = (item.get("home") or "").strip() or "your home"
    vals = {"greeting": greeting(item.get("first")), "home": home, "booking_link": booking_link or MISSING_LINK,
            "first": item.get("first") or ""}
    return re.sub(r"\{(greeting|home|booking_link|first)\}", lambda m: vals[m.group(1)], template)


def skeleton(item, templates, booking_link):
    key = item.get("template") or ""
    t = templates.get(key)
    return fill(t, item, booking_link) if t else ""


def check(text, context, require_link=False):
    """The copy checker's verdict, trimmed: {"ok", "grade", "blocking": [...], "warnings": [...]}."""
    from tools.copy_check.check import check as cc
    r = cc(text, context, require_link=require_link)
    slim = lambda i: {k: i.get(k) for k in ("rule", "match", "line", "fix")}  # noqa: E731
    return {"ok": bool(r.get("ok")), "grade": r.get("grade"), "context": r.get("context", context),
            "blocking": [slim(i) for i in r.get("issues") or [] if i.get("severity") == "block"],
            "warnings": [slim(i) for i in r.get("issues") or [] if i.get("severity") != "block"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--file", required=True)
    c.add_argument("--context", required=True, choices=("prospect_email", "prospect_sms", "client", "internal"))
    c.add_argument("--require-link", action="store_true")
    a = ap.parse_args(argv)
    with open(a.file, encoding="utf-8") as f:
        text = f.read()
    res = check(text, a.context, a.require_link)
    print(json.dumps(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
