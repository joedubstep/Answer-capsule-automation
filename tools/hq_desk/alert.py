"""Decide whether Joey gets ONE short text, and write it.

  python3 -m tools.hq_desk.alert [--desk /tmp/hq_desk/desk.json] [--prev <last published page>]
                                 [--url <artifact url>] [--out /tmp/hq_desk/sms.txt]

Texts only when something is new and urgent since the last published page: a new hot lead, an owed item that
now has a draft, or a health flag that just turned red. The last page carries its state (hashed ids only), so
no other storage is needed. Prints "TEXT: <message>" and writes --out, or "NO TEXT: <why>" and removes --out.
"""
import argparse
import json
import os
import re
import sys

from tools.hq_desk import profile as prof
from tools.hq_desk.render import state_of, visible_items

MAX_CHARS = 320
STATE_RX = re.compile(r'<script type="application/json" id="desk-state">(.*?)</script>', re.S)


def read_prev_state(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        m = STATE_RX.search(f.read())
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("<\\/", "</"))
    except ValueError:
        return None


def who(l):
    bits = [x for x in (l.get("code"), l.get("first")) if x]
    return " ".join(bits) or "a lead"


def decide(desk, prev, url=""):
    """(message or "", reason)"""
    shown, _ = visible_items(desk)
    cur = state_of(desk, shown)
    prev = prev or {"hot": [], "owed_drafted": [], "red": []}
    by_hash = {l["hash"]: l for l in desk.get("items", [])}
    new_hot = [h for h in cur["hot"] if h not in set(prev.get("hot") or [])]
    new_owed = [k for k in cur["owed_drafted"] if k not in set(prev.get("owed_drafted") or [])]
    new_red = [k for k in cur["red"] if k not in set(prev.get("red") or [])]
    if not (new_hot or new_owed or new_red):
        return "", "nothing new and urgent"
    parts = []
    if new_hot:
        names = [who(by_hash[h]) for h in new_hot if h in by_hash]
        more = f" +{len(names) - 3}" if len(names) > 3 else ""
        parts.append(f"{len(new_hot)} new hot: {', '.join(names[:3])}{more}.")
    if new_owed:
        leads = []
        for k in new_owed:
            l = by_hash.get(k.split(":")[0])
            if l and who(l) not in leads:
                leads.append(who(l))
        parts.append(f"{len(new_owed)} owed {'item' if len(new_owed) == 1 else 'items'} drafted: {', '.join(leads[:3])}.")
    if new_red:
        texts = [f["text"] for f in desk.get("health") or [] if f["key"] in new_red]
        parts.append("Red: " + " ".join(texts[:2]) + (f" +{len(texts) - 2} more." if len(texts) > 2 else ""))
    msg = "Desk: " + " ".join(parts)
    tail = (" " + url) if url else ""
    if len(msg) + len(tail) > MAX_CHARS:
        msg = msg[:MAX_CHARS - len(tail) - 3].rstrip() + "..."
    return msg + tail, f"{len(new_hot)} new hot, {len(new_owed)} owed drafted, {len(new_red)} new red"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Decide on one text to Joey.")
    ap.add_argument("--desk", default=os.path.join(prof.OUT_DIR, "desk.json"))
    ap.add_argument("--prev", help="the page as last published (from the Artifact read)")
    ap.add_argument("--url", default=prof.resolve("hq")["artifact_url"] if os.path.exists(prof.CONFIG) else "")
    ap.add_argument("--out", default=os.path.join(prof.OUT_DIR, "sms.txt"))
    a = ap.parse_args(argv)
    with open(a.desk, encoding="utf-8") as f:
        desk = json.load(f)
    msg, why = decide(desk, read_prev_state(a.prev), a.url)
    if msg:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(msg)
        print("TEXT: " + msg)
    else:
        if os.path.exists(a.out):
            os.remove(a.out)
        print("NO TEXT: " + why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
