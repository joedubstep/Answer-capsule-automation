"""Build the Copy Checker page (the artifact Joey opens on his phone or laptop).

    python3 -m tools.copy_check.build_page --out /tmp/copy_checker.html
    python3 -m tools.copy_check.build_page --out /tmp/copy_checker_local.html --standalone

The page embeds the compiled rules.json and the JavaScript port of check.py, so it works with no
network and no external scripts. Default output is artifact-ready: the Artifact publish step wraps it
in its own <!doctype html> skeleton. --standalone adds that skeleton for opening the file directly.
"""
import argparse
import json
import os
import sys

from shared import et
from tools.copy_check.check import HERE, compile_rules, load_rules

TEMPLATE = os.path.join(HERE, "page_template.html")
STANDALONE_HEAD = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                   '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                   '</head>\n<body>\n')
STANDALONE_TAIL = "\n</body>\n</html>\n"


def rules_json_for_html(compiled):
    """JSON safe to put inside <script type="application/json">: no '<', '>' or '&' characters."""
    s = json.dumps(compiled, ensure_ascii=True, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def built_at(now=None):
    d = et.to_et(now) if now else et.now_et()
    hour = d.hour % 12 or 12
    return "%s %d, %d at %d:%02d %s ET" % (d.strftime("%b"), d.day, d.year, hour, d.minute,
                                           "AM" if d.hour < 12 else "PM")


def build(rules_path=None, standalone=False, now=None):
    compiled = compile_rules(load_rules(rules_path))
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    for key in ("__RULES_JSON__", "__BUILT_AT__", "__RULE_COUNT__"):
        if html.count(key) < 1:
            raise RuntimeError("page template is missing " + key)
    html = (html.replace("__RULES_JSON__", rules_json_for_html(compiled))
            .replace("__BUILT_AT__", built_at(now))
            .replace("__RULE_COUNT__", str(len(compiled["rules"]))))
    if standalone:
        html = STANDALONE_HEAD + html + STANDALONE_TAIL
    return html


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m tools.copy_check.build_page")
    ap.add_argument("--out", required=True, help="where to write the HTML page")
    ap.add_argument("--standalone", action="store_true", help="add a full HTML skeleton for local viewing")
    ap.add_argument("--rules", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    html = build(a.rules, a.standalone)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote %s (%d KB)" % (a.out, (len(html.encode("utf-8")) + 1023) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
