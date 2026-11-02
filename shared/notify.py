"""Text Joey through Surven HQ GoHighLevel (works only in the Surven HQ cloud environment).

Same channel the follow-up planner uses for "Calls today": an SMS from the HQ location to
Joey's own alert contact. Rules: never in quiet hours (11pm-5am ET) unless --force; split at
1,500 characters; read each part back. Prints one line. Exit 0 sent, 1 failed, 3 held.

  python3 -m shared.notify --file msg.txt [--force] [--dry-run]
"""
import argparse
import sys
import time

from shared import ghl, et

HQ_LOCATION = "EeadFhXhDOJ1DWE4ArhK"
JOEY_HQ_CONTACT = "ITgRAUyt3KqdPbQB5cUo"
LIMIT = 1500
QUIET_FROM, QUIET_TO = 23, 5


def split(text, limit=LIMIT):
    text = text.strip()
    if len(text) <= limit:
        return [text]
    room = limit - 8  # leave space for the "(1/2)" suffix
    blocks = []
    for line in text.split("\n"):
        while len(line) > room:          # hard-wrap a single over-long line, never drop text
            cut = line.rfind(" ", 0, room)
            cut = cut if cut > room // 2 else room
            blocks.append(line[:cut])
            line = line[cut:].lstrip()
        blocks.append(line)
    parts, cur = [], ""
    for block in blocks:
        add = (("\n" if cur else "") + block)
        if len(cur) + len(add) > room:
            if cur:
                parts.append(cur)
            cur = block
        else:
            cur += add
    if cur:
        parts.append(cur)
    n = len(parts)
    return [f"{p}\n({i + 1}/{n})" for i, p in enumerate(parts)] if n > 1 else parts


def quiet(now=None):
    h = et.to_et(now or et.now_utc()).hour
    return h >= QUIET_FROM or h < QUIET_TO


def text_joey(text, force=False, dry_run=False):
    if not text.strip():
        return 0, "nothing to send"
    if quiet() and not force:
        return 3, "held: quiet hours"
    parts = split(text)
    if dry_run:
        return 0, f"dry run: {len(parts)} part(s), {len(text)} chars"
    states = []
    for p in parts:
        r = ghl.call("/conversations/messages", method="POST", ver=ghl.V_CONV,
                     body={"type": "SMS", "contactId": JOEY_HQ_CONTACT, "message": p})
        mid = r.get("messageId") or r.get("id") if ghl.ok(r) else None
        state = "no message id" if not mid else "unknown"
        for _ in range(6):
            if not mid:
                break
            time.sleep(3)
            m = ghl.call(f"/conversations/messages/{mid}", ver=ghl.V_CONV)
            m = m.get("message", m) if ghl.ok(m) else {}
            state = m.get("status") or "unknown"
            if state not in ("pending", "queued", "unknown", ""):
                break
        states.append(state)
        time.sleep(1)
    bad = [s for s in states if s in ("failed", "undelivered", "no message id")]
    return (1 if bad else 0), f"text: {len(parts)} part(s), status {', '.join(states)}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    with open(a.file, encoding="utf-8") as f:
        code, line = text_joey(f.read(), a.force, a.dry_run)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
