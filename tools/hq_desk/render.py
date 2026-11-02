"""Render the desk as one phone-first HTML page for the HQ Desk artifact.

  python3 -m tools.hq_desk.render [--desk /tmp/hq_desk/desk.json] [--out /tmp/hq_desk/hq_desk.html]

No external scripts, the brand palette, dark mode, copy buttons, a "last updated" line, and no phone numbers or
email addresses: each lead is first name + home + code (Joey texts the code to bridge a call). The page also
carries a small state block (hashed lead ids only) so the next run can tell what is new.
"""
import argparse
import html
import json
import os
import re
import sys

from tools.hq_desk import profile as prof
from tools.hq_desk.score import plural, scrub

E = html.escape

CSS = """
/* One narrow column, ranked cards, summary first: Joey reads this on his phone at 6am. */
:root {
  --bg: #f2eee3; --card: #faf7ef; --fg: #181b18; --muted: #585d52; --line: #c8c1b1;
  --accent: #4e6242; --accent-soft: #e3e7da; --on-accent: #faf7ef;
  --red: #9e2f1c; --red-soft: #f5e0d9; --amber: #7d5f12; --amber-soft: #f1e8cf;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #131512; --card: #1c1f1a; --fg: #ebe7dc; --muted: #a7ab9e; --line: #3a3e35;
    --accent: #a3bb91; --accent-soft: #263024; --on-accent: #131512;
    --red: #f2917b; --red-soft: #3b201a; --amber: #e2c26e; --amber-soft: #322a15; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #131512; --card: #1c1f1a; --fg: #ebe7dc; --muted: #a7ab9e; --line: #3a3e35;
  --accent: #a3bb91; --accent-soft: #263024; --on-accent: #131512;
  --red: #f2917b; --red-soft: #3b201a; --amber: #e2c26e; --amber-soft: #322a15; color-scheme: dark;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 16px/1.45 var(--font); }
.wrap { max-width: 640px; margin: 0 auto; padding-block: 20px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 20px; }
header { display: grid; gap: 6px; }
.eyebrow { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
h1 { font-size: 23px; line-height: 1.25; margin: 0; text-wrap: balance; font-weight: 700; }
.stamp { margin: 0; color: var(--muted); font-size: 13px; }
h2 { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 8px; }
.flags { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.flag { display: grid; grid-template-columns: 10px 1fr; gap: 10px; align-items: baseline; font-size: 15px;
  padding: 8px 10px; border-radius: 8px; }
.flag .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); transform: translateY(-1px); }
.flag.red { background: var(--red-soft); color: var(--fg); }
.flag.red .dot { background: var(--red); }
.flag.red strong { color: var(--red); }
.flag.amber .dot { background: var(--amber); }
.flag .codes { color: var(--muted); font-size: 13px; font-family: var(--mono); }
.leads { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
.lead { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; display: grid; gap: 10px; min-width: 0; }
.head { display: flex; align-items: flex-start; gap: 10px; }
.rank { font-family: var(--mono); color: var(--muted); font-size: 13px; padding-top: 3px; min-width: 18px; }
.title { flex: 1; min-width: 0; display: grid; gap: 4px; }
.title h3 { margin: 0; font-size: 18px; line-height: 1.25; overflow-wrap: anywhere; }
.title .home { color: var(--muted); font-weight: 400; }
.badge { justify-self: start; font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }
.badge.hot { background: var(--red-soft); color: var(--red); }
.code { font: 700 15px var(--mono); padding: 6px 10px; border-radius: 8px; border: 1px solid var(--accent);
  background: var(--accent); color: var(--on-accent); cursor: pointer; }
.code.none { background: transparent; color: var(--muted); border-color: var(--line); cursor: default; font-weight: 400; font-size: 12px; }
.why { margin: 0; padding-left: 18px; display: grid; gap: 2px; }
.facts { margin: 0; display: grid; gap: 4px; }
.facts div { display: grid; grid-template-columns: 74px 1fr; gap: 8px; }
.facts dt { color: var(--muted); font-size: 13px; padding-top: 2px; }
.facts dd { margin: 0; min-width: 0; }
.said { margin: 0; padding: 8px 10px; border-left: 3px solid var(--line); color: var(--fg); font-size: 15px; overflow-wrap: anywhere; }
.said cite { display: block; color: var(--muted); font-size: 12px; font-style: normal; margin-top: 4px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); }
.draft { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 6px; min-width: 0; }
.dhead { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.dlabel { font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 700; }
.copy { font: 600 14px var(--font); padding: 6px 14px; border-radius: 8px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); cursor: pointer; }
.copy:focus-visible, .code:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 15px/1.45 var(--font); background: var(--bg);
  border-radius: 8px; padding: 10px; }
.subj { font-weight: 600; }
.note { margin: 0; font-size: 13px; color: var(--muted); }
.note.warn { color: var(--amber); }
.note.block { color: var(--red); }
details.owed { border-top: 1px solid var(--line); padding-top: 8px; }
details.owed summary { cursor: pointer; font-weight: 600; font-size: 15px; }
.owed-list { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 12px; }
.owed-list li { display: grid; gap: 6px; }
.src { font-size: 13px; overflow-wrap: anywhere; }
.src a { color: var(--accent); }
.need { margin: 0; font-size: 14px; padding: 6px 8px; border-radius: 6px; background: var(--amber-soft); }
footer { color: var(--muted); font-size: 13px; display: grid; gap: 4px; }
.empty { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
"""

JS = """
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-copy],[data-target]');
  if (!b) return;
  var el = b.hasAttribute('data-target') ? document.getElementById(b.getAttribute('data-target')) : null;
  var txt = b.hasAttribute('data-copy') ? b.getAttribute('data-copy') : (el ? el.textContent : '');
  var label = b.getAttribute('data-label') || b.textContent;
  b.setAttribute('data-label', label);
  function say(t) { b.textContent = t; setTimeout(function () { b.textContent = label; }, 1500); }
  function pick() {
    if (el) { var r = document.createRange(); r.selectNodeContents(el); var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); }
    say(el ? 'Selected' : 'Copy failed');
  }
  try { navigator.clipboard.writeText(txt).then(function () { say('Copied'); }, pick); } catch (err) { pick(); }
});
"""


def _safe_url(u):
    u = str(u or "").strip()
    return u if re.match(r"^https://[^\s\"'<>]+$", u) else ""


def state_of(desk, shown):
    """What the next run compares against: hashed ids only, never names."""
    owed_drafted = []
    for l in shown:
        n_due = sum(1 for x in l.get("owed") or [] if x.get("due"))
        for o in (l.get("drafts") or {}).get("owed") or []:
            i = o.get("for")
            if (isinstance(i, int) and 0 <= i < n_due and o.get("text")
                    and (o.get("check") or {}).get("status") != "blocked"):
                owed_drafted.append(f"{l['hash']}:{i}")
    return {
        "v": 1,
        "date": (desk.get("generated_at") or "")[:10],
        "hot": sorted(l["hash"] for l in desk.get("items", []) if "hot" in l["buckets"]
                      and not (l.get("drafts") or {}).get("hide")),
        "owed_drafted": sorted(owed_drafted),
        "red": sorted(f["key"] for f in desk.get("health", []) if f["level"] == "red"),
    }


def visible_items(desk):
    items = [l for l in desk.get("items", []) if not (l.get("drafts") or {}).get("hide")]
    return items[:desk.get("cap", 15)], items[desk.get("cap", 15):]


def top_line(desk, shown):
    call = sum(1 for l in shown if {"hot", "deciding"} & set(l["buckets"]))
    owed_due = sum(sum(1 for x in l["owed"] if x.get("due")) for l in shown)
    ready = len(state_of(desk, shown)["owed_drafted"])
    n7 = (desk.get("top") or {}).get("booked_next_7", 0)
    owed_part = (f"{plural(ready, 'owed item')} ready" if ready else f"{plural(owed_due, 'owed item')} waiting")
    who = "owner" if desk.get("location_key") in (None, "hq") else "lead"
    return f"{plural(call, who)} to call today, {owed_part}, {plural(n7, 'call')} booked next week"


def check_note(chk):
    if not chk:
        return ""
    st = chk.get("status")
    issues = chk.get("issues") or []
    rules = ", ".join(sorted({str(i.get("rule") or i.get("match") or "rule") for i in issues}))
    if st == "blocked":
        return f'<p class="note block">Held by the copy checker ({E(rules)}). Fix before sending.</p>'
    parts = []
    if st == "warn" and issues:
        tips = "; ".join(E(str(i.get("fix") or i.get("rule") or "")) for i in issues[:3])
        parts.append(f'<p class="note warn">Check: {tips}</p>')
    if chk.get("checker") != "copy_check":
        parts.append('<p class="note">Copy checker not installed yet. Basic checks only.</p>')
    return "".join(parts)


def draft_block(label, uid, text, subject=None, chk=None):
    if (chk or {}).get("status") == "blocked":
        return f'<div class="draft"><div class="dhead"><span class="dlabel">{E(label)}</span></div>{check_note(chk)}</div>'
    subj = ""
    if subject:
        subj = (f'<div class="dhead"><span class="subj" id="{uid}s">{E(subject)}</span>'
                f'<button class="copy" type="button" data-target="{uid}s">Copy subject</button></div>')
    return (f'<div class="draft"><div class="dhead"><span class="dlabel">{E(label)}</span>'
            f'<button class="copy" type="button" data-target="{uid}">Copy</button></div>{subj}'
            f'<pre class="text" id="{uid}">{E(text)}</pre>{check_note(chk)}</div>')


def owed_block(l, uid):
    due = [x for x in l["owed"] if x.get("due")]
    later = [x for x in l["owed"] if not x.get("due")]
    drafts = (l.get("drafts") or {}).get("owed") or []
    if not due and not later and not drafts:
        return ""
    ages = [x["age_days"] for x in due if x.get("age_days") is not None]
    summ = f"Owed: {plural(len(due), 'item')}" + (f", oldest {plural(max(ages), 'day')}" if ages else "")
    if not due:
        summ = f"Coming up: {plural(len(later), 'promise')}"
    rows = []
    for i, x in enumerate(due + later):
        age = x.get("age_days")
        when = ("" if age is None else (f" ({plural(age, 'day')} waiting)" if age > 0 else
                                         (" (due today)" if age == 0 else f" (due in {plural(-age, 'day')})")))
        d = next((o for o in drafts if x.get("due") and str(o.get("for")) == str(i)), None)
        inner = [f"<div>{E(scrub(x['text']))}{E(when)}</div>"]
        if d:
            if d.get("text"):
                kind = {"email": "Email draft", "sms": "Text draft"}.get(d.get("kind"), "Draft")
                inner.append(draft_block(kind, f"{uid}o{i}", d["text"], d.get("subject"), d.get("check")))
            srcs = [u for u in (_safe_url(s) for s in d.get("sources") or []) if u]
            if srcs:
                links = []
                for u in srcs:
                    short = re.sub(r"^https://(www\.)?", "", u)[:60]
                    links.append(f'<a href="{E(u)}" target="_blank" rel="noopener">{E(short)}</a>')
                inner.append('<div class="src">Sources: ' + " ".join(links) + "</div>")
            if d.get("missing"):
                inner.append(f'<p class="need">Needs from you: {E(scrub(d["missing"]))}</p>')
            if d.get("done"):
                inner.append(f'<p class="note">Looks done already: {E(scrub(d["done"]))}</p>')
        rows.append("<li>" + "".join(inner) + "</li>")
    return f'<details class="owed"><summary>{E(summ)}</summary><ul class="owed-list">{"".join(rows)}</ul></details>'


def card(l, rank):
    uid = "d" + l["hash"]
    dr = l.get("drafts") or {}
    code = (f'<button class="code" type="button" data-copy="{E(l["code"])}" aria-label="Copy code {E(l["code"])}">'
            f'{E(l["code"])}</button>') if l.get("code") else '<span class="code none">no code</span>'
    home = f' <span class="home">{E(scrub(l["home"]))}</span>' if l.get("home") else ""
    badge = "badge hot" if l["primary"] == "hot" else "badge"
    why = "".join(f"<li>{E(scrub(w))}</li>" for w in l["why"])
    action = scrub(dr.get("action") or l["action"])
    facts = f'<div><dt>Waiting</dt><dd>{E(l["waiting"] or "today")}</dd></div><div><dt>Next</dt><dd>{E(action)}</dd></div>'
    if dr.get("note"):
        facts += f'<div><dt>Note</dt><dd>{E(scrub(dr["note"]))}</dd></div>'
    said = ""
    if l.get("said"):
        s = l["said"]
        said = f'<blockquote class="said">{E(s["text"])}<cite>{E(s["channel"])}, {E(s["ago"])} ago</cite></blockquote>'
    chips = "".join(f'<span class="chip">{E(c)}</span>' for c in l.get("chips") or [])
    chips = f'<div class="chips">{chips}</div>' if chips else ""
    drafts = ""
    if (dr.get("sms") or {}).get("text") or (dr.get("sms") or {}).get("check"):
        drafts += draft_block("Text draft", uid + "t", dr["sms"].get("text") or "", None, dr["sms"].get("check"))
    if (dr.get("email") or {}).get("text") or (dr.get("email") or {}).get("check"):
        drafts += draft_block("Email draft", uid + "e", dr["email"].get("text") or "", dr["email"].get("subject"),
                              dr["email"].get("check"))
    return (f'<li class="lead" id="l{l["hash"]}"><div class="head"><span class="rank">{rank}</span>'
            f'<div class="title"><span class="{badge}">{E(l["label"])}</span>'
            f'<h3>{E(scrub(l["first"]) or "No name")}{home}</h3></div>{code}</div>'
            f'<ul class="why">{why}</ul><dl class="facts">{facts}</dl>{said}{chips}{drafts}{owed_block(l, uid)}</li>')


def render(desk):
    shown, rest = visible_items(desk)
    hidden = [l for l in desk.get("items", []) if (l.get("drafts") or {}).get("hide")]
    loc = desk.get("location_key") or "hq"
    eyebrow = "Surven HQ desk" if loc == "hq" else f"Test run on {E(loc.upper())} data"
    flags = []
    for f in desk.get("health") or []:
        cls = "flag " + (f["level"] if f["level"] in ("red", "amber") else "ok")
        text = E(f["text"])
        if f["level"] == "red":
            text = f"<strong>{text}</strong>"
        codes = f' <span class="codes">{E(", ".join(f["codes"]))}</span>' if f.get("codes") and f["level"] != "ok" else ""
        flags.append(f'<li class="{cls}"><span class="dot"></span><span>{text}{codes}</span></li>')
    if desk.get("fatal"):
        flags.insert(0, f'<li class="flag red"><span class="dot"></span><span><strong>{E(desk["fatal"])}</strong></span></li>')
    cards = "".join(card(l, i + 1) for i, l in enumerate(shown))
    if not cards:
        cards = '<li class="empty">Nobody needs you right now. The planner has the rest.</li>'
    c = desk.get("counts") or {}
    foot = [f"Showing {len(shown)} of {plural(c.get('candidates', 0), 'lead')} who need something."]
    if rest:
        foot.append(f"{len(rest)} more are in the follow-up planner's list.")
    parts = [f"{plural(c.get(k, 0), n)}" for k, n in (("hot", "hot lead"), ("deciding", "deciding"),
                                                       ("rebook", "rebook"), ("stale_replied", "reply waiting"),
                                                       ("warm_referral", "warm referral"))]
    foot.append("All told: " + ", ".join(parts) + f", {plural(c.get('owed_items', 0), 'owed item')}.")
    if hidden:
        foot.append(f"Left off after review: {len(hidden)}.")
    bound = next((e[1] for e in desk.get("errors") or [] if e and e[0] == "bound"), "")
    if bound:
        foot.append(f"Read limit hit: {bound}.")
    foot.append("Tap a code to copy it. Text the code to bridge a call.")
    state = json.dumps(state_of(desk, shown)).replace("</", "<\\/")
    return (
        '<title>HQ Deal Desk</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
        f"<style>{CSS}</style>\n"
        f'<main class="wrap"><header><div class="eyebrow">{eyebrow}</div>'
        f"<h1>{E(top_line(desk, shown))}</h1>"
        f'<p class="stamp">Last updated {E(desk.get("generated_et") or "")} ET</p></header>'
        f'<section aria-label="Health"><h2>Health</h2><ul class="flags">{"".join(flags)}</ul></section>'
        f'<section aria-label="Leads"><h2>Closest to money</h2><ol class="leads">{cards}</ol></section>'
        f'<footer>{"".join(f"<div>{E(x)}</div>" for x in foot)}</footer></main>\n'
        f'<script type="application/json" id="desk-state">{state}</script>\n'
        f"<script>{JS}</script>\n"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the HQ desk page.")
    ap.add_argument("--desk", default=os.path.join(prof.OUT_DIR, "desk.json"))
    ap.add_argument("--out", default=os.path.join(prof.OUT_DIR, "hq_desk.html"))
    a = ap.parse_args(argv)
    with open(a.desk, encoding="utf-8") as f:
        desk = json.load(f)
    page = render(desk)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"page: {len(page)} bytes -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
