"""Render the Client Desk pages.

  render_page(view)    -> the Joey-facing ops page (one artifact per client): top line, numbers, unknown-caller
                          triage, unanswered messages, the Monday partner call list and open rooms email, the Friday
                          owner report preview and its short text, partner stages, copy buttons.
  render_report(rep)   -> the client-facing owner report (report.html, published as its own private page). Surven's brand:
                          cream, sage and ink, Cormorant Garamond headings and DM Sans text through system fallbacks.

  python3 -m tools.client_desk.render --view /tmp/client_desk/agc/view.json --out /tmp/client_desk/agc/client_desk.html

No external scripts or fonts. No phone numbers and no email addresses: families are first name + code, partners are
place + P code, unknown callers are "Caller" + the last 4 digits.
"""
import argparse
import html
import json
import re
import sys

from shared import et
from tools.client_desk import metrics as M
from tools.client_desk import checks as C

E = html.escape

FONTS = """
  --display: "Cormorant Garamond", "Cormorant", Georgia, "Times New Roman", serif;
  --font: "DM Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;"""

TOKENS_LIGHT = """
  --bg: #f2eee3; --card: #faf7ef; --fg: #181b18; --muted: #585d52; --line: #c8c1b1;
  --accent: #4e6242; --accent-soft: #e3e7da; --on-accent: #faf7ef;
  --red: #9e2f1c; --red-soft: #f5e0d9; --amber: #7d5f12; --amber-soft: #f1e8cf; --mark: #f3dd9b;"""
TOKENS_DARK = """
  --bg: #131512; --card: #1c1f1a; --fg: #ebe7dc; --muted: #a7ab9e; --line: #3a3e35;
  --accent: #a3bb91; --accent-soft: #263024; --on-accent: #131512;
  --red: #f2917b; --red-soft: #3b201a; --amber: #e2c26e; --amber-soft: #322a15; --mark: #5a4a17; color-scheme: dark;"""

BASE_CSS = """
:root {%s%s
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {%s
  }
}
:root[data-theme="dark"] {%s
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%%; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 var(--font); }
.wrap { max-width: 680px; margin: 0 auto; padding-block: 20px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 22px; }
h1, h2, h3 { font-family: var(--display); font-weight: 600; margin: 0; line-height: 1.15; text-wrap: balance; }
h1 { font-size: 34px; }
h2 { font-size: 26px; }
h3 { font-size: 20px; }
a { color: var(--accent); }
.eyebrow { font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); font-weight: 700; margin: 0; }
.stamp, .muted { color: var(--muted); font-size: 14px; margin: 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: grid; gap: 12px; min-width: 0; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px; display: grid; gap: 2px; min-width: 0; }
.tile .n { font-family: var(--display); font-size: 30px; font-weight: 600; line-height: 1.05; overflow-wrap: anywhere; }
.tile .k { font-size: 13px; color: var(--muted); }
.tile.red .n { color: var(--red); }
ul.plain { margin: 0; padding-left: 20px; display: grid; gap: 4px; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
""" % (TOKENS_LIGHT, FONTS, TOKENS_DARK, TOKENS_DARK)

PAGE_CSS = """
.top { font-family: var(--display); font-size: 22px; line-height: 1.3; margin: 0; }
section { display: grid; gap: 12px; }
.sechead { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.copy { font: 600 14px var(--font); padding: 6px 14px; border-radius: 8px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); cursor: pointer; }
.copy.solid { background: var(--accent); color: var(--on-accent); }
.copy:focus-visible, summary:focus-visible, a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 15px/1.5 var(--font); background: var(--bg);
  border-radius: 8px; padding: 12px; border: 1px solid var(--line); }
.text mark { background: var(--mark); color: inherit; border-radius: 3px; padding: 0 2px; font-weight: 700; }
.text .mf { color: var(--accent); font-family: var(--mono); font-size: 13px; }
.chip { display: inline-block; font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }
.chip.robo { background: var(--line); color: var(--fg); }
.chip.fam { background: var(--red-soft); color: var(--red); }
.chip.unclear { background: var(--amber-soft); color: var(--amber); }
.chip.nf { background: var(--accent-soft); color: var(--muted); }
.caller { display: grid; gap: 6px; padding: 12px 0; border-top: 1px solid var(--line); }
.caller:first-of-type { border-top: 0; padding-top: 0; }
.caller .row1 { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.caller .name { font-weight: 700; font-family: var(--mono); }
.caller p { margin: 0; }
.ev { margin: 0; padding-left: 18px; color: var(--muted); font-size: 14px; display: grid; gap: 2px; }
.heard { font-style: italic; color: var(--fg); }
.rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; }
.rows li { display: grid; gap: 2px; padding: 10px 0; border-top: 1px solid var(--line); }
.rows li:first-child { border-top: 0; }
.rows .l1 { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.rows .who { font-weight: 700; overflow-wrap: anywhere; }
.rows .when { color: var(--muted); font-size: 14px; white-space: nowrap; }
.rows .l2 { color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
details > summary { cursor: pointer; font-weight: 600; }
.ask { margin: 0; padding: 10px 12px 10px 28px; background: var(--accent-soft); border-radius: 10px; display: grid; gap: 4px; font-size: 15px; }
.flag { margin: 0; padding: 8px 10px; border-radius: 8px; font-size: 14px; background: var(--amber-soft); }
.flag.red { background: var(--red-soft); }
.ok { color: var(--accent); }
.held { color: var(--red); font-weight: 700; }
table.stages { border-collapse: collapse; width: 100%; font-size: 15px; }
table.stages td, table.stages th { padding: 6px 4px; border-bottom: 1px solid var(--line); text-align: left; }
table.stages td.n, table.stages th.n { text-align: right; font-variant-numeric: tabular-nums; }
footer { color: var(--muted); font-size: 13px; display: grid; gap: 4px; }
.preview { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
"""

REPORT_CSS = """
.rp { display: grid; gap: 22px; }
.rp-head { display: grid; gap: 6px; border-bottom: 2px solid var(--accent); padding-bottom: 14px; }
.rp-head h1 { font-size: 38px; }
.rp-sec { display: grid; gap: 10px; }
.rp-sec h2 { font-size: 26px; color: var(--accent); }
.rp-sec p { margin: 0; }
.rp-foot { color: var(--muted); font-size: 13px; border-top: 1px solid var(--line); padding-top: 12px; }
@media print {
  :root { --bg: #ffffff; --card: #ffffff; --fg: #181b18; --muted: #585d52; --line: #c8c1b1; --accent: #4e6242; color-scheme: light; }
  .wrap { max-width: none; padding: 0; }
  .tile { break-inside: avoid; }
  .rp-sec { break-inside: avoid; }
}
"""

JS = """
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-target]');
  if (!b) return;
  var el = document.getElementById(b.getAttribute('data-target'));
  var txt = el ? (el.getAttribute('data-raw') || el.textContent) : '';
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

VERDICT = {"robocall-likely": ("Robocall likely", "robo"), "family-likely": ("Family likely", "fam"),
           "not-a-family": ("Not a family", "nf"), "unclear": ("Unclear", "unclear")}


def stamp(now_iso):
    t = et.to_et(et.parse(now_iso))
    return "%s %d, %d:%02d%s ET" % (t.strftime("%a %b"), t.day, (t.hour % 12) or 12, t.minute, "am" if t.hour < 12 else "pm")


def when(iso):
    t = M.ts(iso)
    if not t:
        return ""
    t = et.to_et(t)
    return "%s %d, %d:%02d%s" % (t.strftime("%a %b"), t.day, (t.hour % 12) or 12, t.minute, "am" if t.hour < 12 else "pm")


def day(iso):
    t = M.ts(iso)
    return ("%s %d" % (et.to_et(t).strftime("%b"), et.to_et(t).day)) if t else ""


def copy_block(id_, text, label="Copy", html_body=None):
    return ('<pre class="text" id="%s" data-raw="%s">%s</pre>' % (id_, E(text, quote=True), html_body or E(text)),
            '<button class="copy" type="button" data-target="%s">%s</button>' % (id_, E(label)))


def check_line(res):
    if not res:
        return ""
    cls = "ok" if res["ok"] else "held"
    return '<p class="muted"><span class="%s">%s</span></p>' % (cls, E(C.summary(res)))


def tiles(items):
    out = []
    for k, v, red in items:
        out.append('<div class="tile%s"><span class="n">%s</span><span class="k">%s</span></div>' % (
            " red" if red else "", E(str(v)), E(k)))
    return '<div class="tiles">%s</div>' % "".join(out)


# ---------------------------------------------------------------- report (client-facing)

def report_body(rep):
    parts = ['<div class="rp"><header class="rp-head"><p class="eyebrow">Weekly report from Surven</p>'
             '<h1>%s</h1><p class="stamp">%s</p></header>' % (E(rep["home"]), E(rep["period"]))]
    for s in rep["sections"]:
        h = ['<section class="rp-sec"><h2>%s</h2>' % E(s["title"])]
        if s.get("stats"):
            h.append(tiles([(k, v, False) for k, v in s["stats"]]))
        if s.get("list"):
            h.append('<p class="muted">%s</p><ul class="plain">%s</ul>' % (
                E(s.get("list_title") or ""), "".join("<li>%s</li>" % E(x) for x in s["list"])))
        for line in s.get("lines") or []:
            h.append("<p>%s</p>" % E(line))
        if s.get("bullets"):
            h.append('<ul class="plain">%s</ul>' % "".join("<li>%s</li>" % E(b) for b in s["bullets"]))
        h.append("</section>")
        parts.append("".join(h))
    parts.append('<p class="rp-foot">Every number comes from the home\'s own records. A zero means none.</p></div>')
    return "".join(parts)


def render_report(rep, short):
    title = "%s Weekly Report" % short
    # Artifact page contract: no doctype/html/head/body (the publisher wraps the page); title + gutter tag first.
    return ("<title>%s</title>\n<meta name=\"claude:viewport-fit-sides\" content=\"cover\">\n"
            "<style>%s%s</style>\n<main class=\"wrap\">%s</main>\n" % (
                E(title), BASE_CSS, REPORT_CSS, report_body(rep)))


# ---------------------------------------------------------------- ops page (Joey)

def top_line(view):
    d, mode = view["desk"], view["mode"]
    tc = view.get("triage_counts") or {}
    bits = []
    if mode in ("friday", "full"):
        rep = view.get("report") or {}
        ok = all(v and v["ok"] for v in (rep.get("check") or {}).values())
        g = d["goal"]
        goal = (" of %d" % g["move_ins"]) if g.get("move_ins") else ""
        bits.append("Report %s: %d new families, %d toured so far, %d%s move-ins" % (
            "ready" if ok else "HELD", d["families"]["new_week"], d["tours"]["toured_to_date"], d["move_ins"]["to_date"], goal))
    if mode in ("monday", "full") and view.get("call"):
        cc = view["call"]["counts"]
        bits.append("%s to call, %s" % (_n(cc["first_calls"], "partner"), _n(cc["check_ins"], "check-in")))
        em = view.get("email") or {}
        if em and not em.get("skip"):
            bits.append("open rooms email %s for %d" % ("HELD" if any(v and not v["ok"] for v in em["check"].values())
                                                        else "ready", (em.get("recipients") or {}).get("count", 0)))
    n = sum(tc.values())
    if n:
        bits.append("callers: %s" % ", ".join("%d %s" % (v, k.replace("-likely", "").replace("-", " "))
                                              for k, v in tc.items() if v))
    un = len(d.get("unanswered") or [])
    if un:
        bits.append("%d waiting over 24h" % un)
    return "%s %s: %s." % (d["short"], {"monday": "Monday", "friday": "Friday"}.get(mode, "now"), "; ".join(bits) or "nothing new")


def triage_section(view):
    items = view.get("triage") or []
    if not items:
        return ('<section><h2>Unknown callers</h2><div class="card"><p class="muted">No calls from unknown numbers '
                'are waiting.</p></div></section>')
    from tools.client_desk import triage as T
    ans = T.answers_text(items)
    pre, btn = copy_block("triage-answers", ans, "Copy answers")
    cards = []
    for i in items:
        lab, cls = VERDICT[i["verdict"]]
        if i["lean"]:
            lab += ", leans " + i["lean"]
        ev = []
        for c in i["calls"][-4:]:
            dur = ("%d sec" % c["dur"]) if isinstance(c.get("dur"), (int, float)) else "no length"
            line = E("%s, %s, %s" % (when(c["when"]), dur, c["status"] or "call"))
            if c.get("heard"):
                line += ': <span class="heard">"%s"</span>' % E(c["heard"])
            elif c.get("words") is not None and c["words"] <= 2 and c["status"] == "completed":
                line += ", nobody spoke"
            elif c.get("transcript") != "ok" and (c.get("dur") or 0) > 0:
                line += ", no transcript"
            ev.append("<li>%s</li>" % line)
        for t in i.get("texts") or []:
            ev.append('<li>%s, text: <span class="heard">"%s"</span></li>' % (E(when(t["when"])), E(t["text"])))
        cards.append(
            '<div class="caller"><div class="row1"><span class="name">%s</span><span class="chip %s">%s</span>%s</div>'
            '<p>%s</p><ul class="ev">%s</ul><p class="muted"><a href="%s" target="_blank" rel="noopener">Open in '
            'GoHighLevel</a> to listen.</p></div>' % (
                E(i["label"]), cls, E(lab), ' <span class="muted">older, still waiting</span>' if i["older"] else "",
                E(i["reason"][:1].upper() + i["reason"][1:] + "."), "".join(ev), E(i["link"], quote=True)))
    tc = view.get("triage_counts") or {}
    head = ", ".join("%d %s" % (v, VERDICT[k][0].lower()) for k, v in tc.items() if v)
    return ('<section><div class="sechead"><h2>Unknown callers</h2>%s</div><p class="muted">%s. Use these to answer the '
            'planner\'s NEED YOU questions in one pass. You decide; nothing is changed in GoHighLevel.</p>'
            '<div class="card">%s</div><details><summary>Answers as one block</summary>%s</details></section>' % (
                btn, E(head), "".join(cards), pre))


def unanswered_section(view):
    rows = view["desk"].get("unanswered") or []
    if not rows:
        return ""
    lis = "".join('<li><div class="l1"><span class="who">%s</span><span class="when">%s</span></div>'
                  '<div class="l2">%s %s%s</div></li>' % (
                      E(r["label"]), E(_days(r["age_days"])), E(r["channel"]), E(when(r["when"])),
                      (': "%s"' % E(r["preview"][:90])) if r.get("preview") else "") for r in rows[:25])
    return ('<section><h2>Waiting over 24 hours</h2><p class="muted">They wrote or called and nobody from Surven '
            'answered since.</p><div class="card"><ul class="rows">%s</ul></div></section>' % lis)


def _n(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def _days(n):
    n = int(round(n or 0))
    return "%d day%s" % (n, "" if n == 1 else "s")


def partner_rows(rows, limit=None):
    out = []
    for r in rows[:limit] if limit else rows:
        last = ("%s, %s" % (day(r["last_touch"]), r["last_how"])) if r["last_touch"] else r["last_how"]
        extra = []
        if r["type"]:
            extra.append(r["type"])
        if r["tries"]:
            extra.append("%d call%s from us" % (r["tries"], "" if r["tries"] == 1 else "s"))
        if r.get("last_open_rooms_days") is not None:
            extra.append("open rooms email %s ago" % _days(r["last_open_rooms_days"]))
        if not r["has_email"]:
            extra.append("no email on file")
        if r["dnd"]:
            extra.append("do not disturb")
        out.append('<li><div class="l1"><span class="who">%s</span><span class="when">%s</span></div>'
                   '<div class="l2">%s%s</div>%s</li>' % (
                       E(r["label"]), E(_days(r["days"]) if r["days"] is not None else "never"),
                       E(r["stage"] + ". Last: " + last), E((". " + ", ".join(extra)) if extra else ""),
                       ('<div class="l2">%s</div>' % E(r["note"])) if r.get("note") else ""))
    return "".join(out)


def calls_section(view):
    call = view.get("call")
    if call is None:
        return ('<section><h2>Partner calls</h2><div class="card"><p class="muted">No referral partner pipeline in this '
                'account.</p></div></section>')
    blocks = []
    for g in call["groups"]:
        if g["key"] == "weekly_note":
            continue
        n = len(g["rows"])
        ask = '<ul class="ask">%s</ul>' % "".join("<li>%s</li>" % E(a) for a in g["ask"])
        if not n:
            blocks.append('<div class="card"><h3>%s</h3><p class="muted">None this week.</p></div>' % E(g["title"]))
            continue
        first = '<ul class="rows">%s</ul>' % partner_rows(g["rows"], 12)
        more = ""
        if n > 12:
            more = '<details><summary>%d more</summary><ul class="rows">%s</ul></details>' % (n - 12, partner_rows(g["rows"][12:]))
        blocks.append('<div class="card"><h3>%s: %d</h3><p class="muted">What to ask. Your words, these are only the '
                      'points:</p>%s%s%s</div>' % (E(g["title"]), n, ask, first, more))
    return ('<section><h2>Partner calls this week</h2><p class="muted">Oldest touch first. Text the P code to bridge '
            'the call.</p>%s</section>' % "".join(blocks))


def mark_body(body):
    h = E(body)
    h = h.replace("[N]", "<mark>[N]</mark>")
    return re.sub(r"\{\{[^{}]+\}\}", lambda m: '<span class="mf">%s</span>' % m.group(0), h)


def email_section(view):
    em = view.get("email")
    if not em:
        return ""
    if em.get("skip"):
        return '<section><h2>Open rooms email</h2><div class="card"><p class="muted">%s</p></div></section>' % E(em["skip"])
    chk = em["check"]
    held = [k for k, v in chk.items() if v and not v["ok"]]
    parts = ['<section><h2>Open rooms email</h2>']
    rc = em.get("recipients") or {}
    info = ['Fill the <mark>[N]</mark> blanks (%d) after the owner tells you which rooms are open.' % em["blanks"]]
    if em.get("last_sent"):
        ls = em["last_sent"]
        subs = [s for s in ls.get("subjects") or [] if s]
        info.append("Last sent %s to %s%s." % (ls["day"], _n(ls["recipients"], "partner"), (
            " (subjects: %s)" % "; ".join('"%s"' % s for s in subs[:3])) if subs else ""))
    info.append("This week's list: %s with an email on file." % _n(rc.get("count", 0), "partner"))
    parts.append('<p class="muted">%s</p>' % " ".join(info))
    flags = []
    if rc.get("no_email"):
        flags.append("No email on file, call them first: " + ", ".join(rc["no_email"][:8]))
    if rc.get("not_tagged"):
        flags.append("Not tagged open-beds-weekly (add the tag if you send by tag): " + ", ".join(rc["not_tagged"][:8]))
    if rc.get("dnd"):
        flags.append("Do not disturb, leave out: " + ", ".join(rc["dnd"][:8]))
    if not em.get("phone_field_ok"):
        flags.append("The account has no phone on its business profile, so {{location.phone}} will be blank. Type the number in.")
    parts += ['<p class="flag">%s</p>' % E(f) for f in flags]
    if held:
        parts.append('<div class="card"><p class="held">Held by the copy checker (%s). Not shown.</p>%s</div>' % (
            E(", ".join(held)), "".join(check_line(chk[k]) for k in held)))
        parts.append("</section>")
        return "".join(parts)
    s_pre, s_btn = copy_block("email-subject", em["subject"], "Copy subject")
    b_pre, b_btn = copy_block("email-body", em["body"], "Copy email", mark_body(em["body"]))
    parts.append('<div class="card"><div class="sechead"><h3>Subject</h3>%s</div>%s<div class="sechead"><h3>Email</h3>%s'
                 '</div>%s%s<p class="muted">Send it from GoHighLevel to the partners due this week. The {{...}} parts '
                 'fill in by themselves.</p></div>' % (s_btn, s_pre, b_btn, b_pre, check_line(chk["body"])))
    if em.get("owner_text") and chk.get("owner_text") and chk["owner_text"]["ok"]:
        o_pre, o_btn = copy_block("owner-text", em["owner_text"], "Copy text")
        parts.append('<div class="card"><div class="sechead"><h3>Text to the owner first</h3>%s</div>%s%s</div>' % (
            o_btn, o_pre, check_line(chk["owner_text"])))
    parts.append("</section>")
    return "".join(parts)


def report_section(view):
    rep = view.get("report")
    if not rep:
        return ""
    chk = rep["check"]
    if not chk["page"]["ok"] or not chk["text"]["ok"]:
        return ('<section><h2>Owner report</h2><div class="card"><p class="held">Held by the copy checker. Fix the words '
                'and run again.</p>%s%s</div></section>' % (check_line(chk["page"]), check_line(chk["text"])))
    t_pre, t_btn = copy_block("report-text", rep["text"], "Copy short text")
    url = view.get("report_url") or ""
    if url:
        link = ('<a class="copy solid" href="%s" target="_blank" rel="noopener">Open report page</a>' % E(url, quote=True))
        how = "open the report page and send the client a screenshot of it"
    else:
        link = ""
        how = "open the report page (its link is in this run's final message) and send the client a screenshot of it"
    return ('<section><div class="sechead"><h2>Owner report</h2>%s</div><p class="muted">Check it, then send it '
            'yourself: %s, or send the short text. Never share this desk page with the client.</p>'
            '<div class="card"><div class="sechead"><h3>Short text</h3>%s</div>%s%s</div>'
            '<details><summary>Preview the report</summary><div class="card preview">%s</div>%s</details></section>' % (
                link, E(how), t_btn, t_pre, check_line(chk["text"]), report_body(rep), check_line(chk["page"])))


def stages_section(view):
    pa = view["desk"].get("partners")
    if not pa:
        return ""
    rows = "".join('<tr><td>%s</td><td class="n">%d</td><td class="n">%s</td></tr>' % (
        E(r["name"]), r["total"], E(str(pa["moves"]["by_stage"].get(r["name"], 0)))) for r in pa["stages"])
    last = pa["moves"]["last_move"]
    lm = ("Last stage change: %s." % day(last)) if last else "No stage change on record."
    t = pa["touches"]
    goal = pa.get("goal") or {}
    g = ""
    if goal:
        g = " Target by %s: %d on the weekly email (now %d), %d referrals (now %d)." % (
            day(goal.get("by") + "T12:00:00Z") if goal.get("by") else "", goal.get("yes_partners") or 0,
            pa["on_weekly_list"], goal.get("referrals") or 0, pa["sent_referral"])
    return ('<section><h2>Partner pipeline</h2><div class="card"><table class="stages"><tr><th>Stage</th>'
            '<th class="n">Deals</th><th class="n">Moved in 7 days</th></tr>%s<tr><td><b>Total</b></td><td class="n">'
            '<b>%d</b></td><td class="n"><b>%d</b></td></tr></table><p class="muted">%s This week: %s to %s, '
            '%s.%s</p></div></section>' % (
                rows, pa["total"], pa["moves"]["moved"], E(lm), _n(t["touches"], "touch", "touches"),
                _n(t["partners_touched"], "partner"), _n(t["partners_replied"], "partner wrote or called back",
                                                          "partners wrote or called back"), E(g)))


def numbers(view):
    d = view["desk"]
    f, t, mi, g = d["families"], d["tours"], d["move_ins"], d["goal"]
    items = [("New families, 7 days", f["new_week"], False),
             ("Half reached within", _short_dur(f["speed_week_min"] if f["speed_week_n"] else f["speed_month_min"]) +
              ("" if f["speed_week_n"] else " (30 days)") if (f["speed_week_n"] or f["speed_month_n"]) else "none", False),
             ("Toured so far", t["toured_to_date"], False),
             ("Move-ins" + (" of %d" % g["move_ins"] if g.get("move_ins") else ""), mi["to_date"], False)]
    if d.get("partners"):
        items.append(("Partners on weekly email", d["partners"]["on_weekly_list"], False))
    items.append(("Waiting over 24h", len(d.get("unanswered") or []), bool(d.get("unanswered"))))
    items.append(("Unknown callers", f["unknown_callers"], bool(f["unknown_callers"])))
    return tiles(items)


def _short_dur(m):
    if m is None:
        return "none"
    if m < 1:
        return "under 1 min"
    if m < 60:
        return "%d min" % round(m)
    if m < 1440:
        return "%.1f h" % (m / 60.0)
    return "%.1f days" % (m / 1440.0)


def footer(view):
    d = view["desk"]
    disc = d.get("discovery") or {}
    bits = []
    for k, lab in (("family_pipeline", "Family pipeline"), ("partner_pipeline", "Partner pipeline"), ("tour_calendar", "Tour calendar")):
        x = disc.get(k) or {}
        bits.append("%s: %s (%s)" % (lab, x.get("name") or "none", x.get("how") or "none"))
    kinds = d.get("kinds") or {}
    who = ", ".join("%s %d" % (k.replace("_", " "), v) for k, v in sorted(kinds.items()))
    t = d["tours"]
    tour_note = ""
    if t["toured_stage_only"]:
        tour_note = ("%d of the toured families show it only on their deal stage or tour result, not on the tour "
                     "calendar." % t["toured_stage_only"])
    errs = d.get("errors") or []
    return ('<footer><p>%s.</p><p>Contacts: %s.</p>%s%s<p>Read-only: nothing was sent, tagged or moved. Drafts go out '
            'only when you send them.</p></footer>' % (
                E("; ".join(bits)), E(who), ("<p>%s</p>" % E(tour_note)) if tour_note else "",
                ('<p class="held">Read errors: %s</p>' % E("; ".join(str(e[0]) for e in errs))) if errs else ""))


def render_page(view):
    d, mode = view["desk"], view["mode"]
    title = "%s Client Desk" % d["short"]
    order = {"monday": [triage_section, unanswered_section, calls_section, email_section, stages_section],
             "friday": [report_section, triage_section, unanswered_section, stages_section],
             "full": [report_section, triage_section, unanswered_section, calls_section, email_section, stages_section]}
    body = "".join(fn(view) for fn in order.get(mode, order["full"]))
    label = {"monday": "Monday run", "friday": "Friday run"}.get(mode, "On-demand run")
    head = ('<header style="display:grid;gap:6px"><p class="eyebrow">Client Desk, %s</p><h1>%s</h1>'
            '<p class="stamp">Last updated %s. %s%s.</p></header>' % (
                E(d["label"]), E(d["label"]), E(stamp(d["now"])), E(label), " (dry run)" if view.get("dry_run") else ""))
    return ("<title>%s</title>\n<meta name=\"claude:viewport-fit-sides\" content=\"cover\">\n"
            "<style>%s%s%s</style>\n<main class=\"wrap\">%s<p class=\"top\">%s</p>%s%s%s</main>\n"
            "<script>%s</script>\n" % (
                E(title), BASE_CSS, PAGE_CSS, REPORT_CSS, head, E(top_line(view)), numbers(view), body, footer(view), JS))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with open(a.view, encoding="utf-8") as f:
        view = json.load(f)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(render_page(view))
    print(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
