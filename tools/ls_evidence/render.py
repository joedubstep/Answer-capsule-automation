"""Render the Lead Suite evidence as one phone-first HTML page for its private artifact.

  python3 -m tools.ls_evidence.render [--evidence /tmp/ls_evidence/evidence.json] [--out /tmp/ls_evidence/ls_evidence.html]

Order: the refund scoreboard, then the rows still to type into the portal (each in the portal's box order with a Copy
button), then the full evidence tables for the refund file. No external scripts, the brand palette, dark mode, and no
phone numbers or emails: each lead is a first name and its reply code. The page carries a small state block (hashed
ids and box answers only) so next week's run knows which rows were already listed.
"""
import argparse
import datetime as dt
import html
import json
import os
import sys

from tools.ls_evidence import profile as prof
from tools.ls_evidence.score import (CALL_BOXES, LEAD_BOXES, NO, NOT_DUE, UNKNOWN, YES, clock, fmt_day, fmt_et, hm,
                                     plural, scrub)

E = html.escape
CLS = {YES: "y", NO: "n", NOT_DUE: "nd", UNKNOWN: "u"}
SHORT = {"triple_dial": "Triple dial", "sms1": "SMS 1", "double_dial": "Double dial", "sms2": "SMS 2", "sms3": "SMS 3",
         "lead_replied": "Replied", "triage": "Triage", "show_sop": "Show SOP", "precall_email": "Pre-call email",
         "morning_confirm": "Morning confirm", "showed": "Showed"}
PROOF = {"crm": ("GHL proves it", "ok"), "partly": ("Partly in GHL", "part"), "outside": ("Outside GHL", "out")}

CSS = """
/* Phone-first: the scoreboard, then the rows to type in on Sunday, then the full proof tables. */
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
body { background: var(--bg); color: var(--fg); font: 16px/1.45 var(--font); margin: 0; }
.wrap { max-width: 720px; margin: 0 auto; padding-block: 20px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 24px; min-width: 0; }
header { display: grid; gap: 6px; }
.eyebrow { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
h1 { font-size: 23px; line-height: 1.25; margin: 0; text-wrap: balance; font-weight: 700; }
h2 { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 10px; }
h3 { font-size: 16px; margin: 0; }
.stamp { margin: 0; color: var(--muted); font-size: 13px; }
section { display: grid; gap: 12px; min-width: 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; display: grid; gap: 10px; min-width: 0; }
.meter { height: 10px; border-radius: 999px; background: var(--accent-soft); overflow: hidden; }
.meter span { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 0; }
.stats div { display: grid; gap: 2px; }
.stats dt { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }
.stats dd { margin: 0; font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.stats dd small { display: block; font-size: 12px; font-weight: 400; color: var(--muted); }
.stand { margin: 0; padding: 10px 12px; border-radius: 8px; background: var(--accent-soft); font-size: 15px; }
details > summary { cursor: pointer; font-weight: 600; font-size: 15px; }
.conds { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 10px; }
.conds li { display: grid; gap: 3px; font-size: 15px; }
.conds .where { color: var(--muted); font-size: 14px; }
.conds .live { font-size: 14px; }
.badge { justify-self: start; font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); }
.badge.part { background: var(--amber-soft); color: var(--amber); }
.badge.out { background: var(--red-soft); color: var(--red); }
.note { margin: 0; font-size: 14px; color: var(--muted); }
.note.warn { color: var(--amber); }
.group { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
.row { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; display: grid; gap: 8px; min-width: 0; }
.row.changed { border-color: var(--amber); }
.rhead { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.who { font-weight: 700; font-size: 17px; overflow-wrap: anywhere; }
.who .code { font: 600 13px var(--mono); color: var(--muted); margin-left: 6px; }
.when { color: var(--muted); font-size: 13px; }
.copy { font: 600 14px var(--font); padding: 6px 14px; border-radius: 8px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); cursor: pointer; white-space: nowrap; }
.copy.solid { background: var(--accent); color: var(--on-accent); }
.copy:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.5 var(--mono); background: var(--bg);
  border-radius: 8px; padding: 10px; }
.why { margin: 0; padding-left: 18px; display: grid; gap: 3px; font-size: 13px; color: var(--muted); }
.why b { color: var(--fg); font-weight: 600; }
.chg { margin: 0; font-size: 13px; color: var(--amber); }
.check { margin: 0; font-size: 13px; color: var(--amber); }
.waiting { margin: 0; font-size: 14px; color: var(--muted); }
.tablewrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--card); max-width: 100%; }
table { border-collapse: collapse; font-size: 13px; width: max-content; min-width: 100%; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; white-space: nowrap; }
th { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); background: var(--card); }
th:first-child, td:first-child { position: sticky; left: 0; background: var(--card); z-index: 1; }
tbody tr:last-child td { border-bottom: 0; }
td small { display: block; color: var(--muted); font-size: 11px; }
.a { font-weight: 700; }
.a.y { color: var(--accent); }
.a.n { color: var(--red); }
.a.nd { color: var(--muted); font-weight: 400; }
.a.u { color: var(--amber); }
.tsv { display: none; }
footer { color: var(--muted); font-size: 13px; display: grid; gap: 6px; }
footer ul { margin: 6px 0 0; padding-left: 18px; display: grid; gap: 3px; }
.empty { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; margin: 0; }
"""

JS = """
function lsCopy(txt, done, fail) {
  function legacy() {
    try {
      var ta = document.createElement('textarea');
      ta.value = txt; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.top = '-1000px';
      document.body.appendChild(ta); ta.select();
      var ok = document.execCommand('copy'); document.body.removeChild(ta);
      if (ok) { done(); } else { fail(); }
    } catch (err) { fail(); }
  }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(txt).then(done, legacy); }
    else { legacy(); }
  } catch (err) { legacy(); }
}
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-target]');
  if (!b) return;
  var ids = b.getAttribute('data-target').split(' ');
  var els = ids.map(function (id) { return document.getElementById(id); }).filter(Boolean);
  var txt = els.map(function (el) { return el.textContent; }).join('\\n\\n');
  var label = b.getAttribute('data-label') || b.textContent;
  b.setAttribute('data-label', label);
  function say(t) { b.textContent = t; setTimeout(function () { b.textContent = label; }, 1500); }
  lsCopy(txt, function () { say('Copied'); }, function () {
    var el = els[0];
    if (el && el.offsetParent !== null) {
      var r = document.createRange(); r.selectNodeContents(el);
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r); say('Selected');
    } else { say('Copy failed'); }
  });
});
"""


def who(r):
    return (scrub(r.get("first")) or "No name") + (f" ({r['code']})" if r.get("code") else " (no code)")


def row_text(r, kind):
    """The exact lines Joey types into the portal, in the portal's box order."""
    order = LEAD_BOXES if kind == "lead" else CALL_BOXES
    head = (f"{who(r)}, lead in {r['t0_et']} ET" if kind == "lead" else f"{who(r)}, call {r['start_et']} ET")
    lines = [head] + [f"{i + 1}. {label}: {r['boxes'][k]['a']}" for i, (k, label) in enumerate(order)]
    if kind == "call":
        n = r.get("notes") or {}
        lines.append("Notes: " + (n.get("text") or "(write 3 to 5 sentences: what they need, beds and timing, what "
                                                  "you offered, the next step)"))
    return "\n".join(lines)


def why_list(r, kind):
    order = LEAD_BOXES if kind == "lead" else CALL_BOXES
    items = [f"<li><b>{i + 1}.</b> {E(scrub(r['boxes'][k]['why']))}</li>" for i, (k, _) in enumerate(order)]
    if kind == "call" and (r.get("notes") or {}).get("src"):
        items.append(f"<li><b>Notes:</b> from the {E(r['notes']['src'])}. Check it before you paste.</li>")
    return f'<details><summary>Why each answer</summary><ul class="why">{"".join(items)}</ul></details>'


def changed_line(was, now_answers, kind):
    order = LEAD_BOXES if kind == "lead" else CALL_BOXES
    names = {"Y": YES, "N": NO, "-": NOT_DUE, "?": UNKNOWN}
    bits = []
    for i, (a, b) in enumerate(zip(was, now_answers)):
        if a != b:
            bits.append(f"box {i + 1} was {names.get(a, a)}, now {names.get(b, b)}")
    return "Changed since it was listed: " + ("; ".join(bits) if bits else "an answer changed") + ". Fix it in the portal."


def row_card(r, kind, uid, was=None):
    checks = "".join(f'<p class="check">Check: {E(scrub(c))}</p>' for c in r.get("checks") or [])
    sub = (f"Lead in {E(r['t0_et'])} ET" if kind == "lead"
           else f"Call {E(r['start_et'])} ET, booked {E(r['booked_et'])}")
    chg = f'<p class="chg">{E(changed_line(was, r["answers"], kind))}</p>' if was else ""
    return (f'<li class="row{" changed" if was else ""}"><div class="rhead"><div><div class="who">'
            f'{E(scrub(r.get("first")) or "No name")}<span class="code">{E(r["code"] or "no code")}</span></div>'
            f'<div class="when">{sub}</div></div>'
            f'<button class="copy" type="button" data-target="{uid}">Copy</button></div>{chg}'
            f'<pre class="text" id="{uid}">{E(row_text(r, kind))}</pre>{checks}{why_list(r, kind)}</li>')


def portal_section(ev):
    p = ev["portal"]
    leads = {r["hash"]: r for r in ev["leads"]}
    calls = {r["hash"]: r for r in ev["calls"]}
    parts = []
    if p.get("first_run"):
        parts.append('<p class="note warn">First run: every finished row since ads went live is listed. Skip the rows '
                     'already in the portal. From next week only new or changed rows show here.</p>')
    else:
        bits = []
        if p.get("prev_date"):
            bits.append(f"Rows already listed on the {E(fmt_day(dt.date.fromisoformat(p['prev_date'])))} page are left out")
        if p.get("entered_through"):
            bits.append(f"rows on or before {E(fmt_day(dt.date.fromisoformat(p['entered_through'])))} count as entered")
        if p.get("relisted") and p.get("entered_through"):
            bits = [f"every finished row after {E(fmt_day(dt.date.fromisoformat(p['entered_through'])))} is listed "
                    f"again, as asked"]
        bits.append("each row shows once")
        text = "; ".join(bits)
        parts.append(f'<p class="note">{text[:1].upper() + text[1:]}. Missed a Sunday? Ask Claude for "lead suite '
                     f'evidence now, entered through" and the last date you typed in: every row after it comes back.</p>')
    for kind, label, add in (("leads", "Leads", "+ Add Lead"), ("calls", "Booked calls", "+ Add Call")):
        src = leads if kind == "leads" else calls
        k1 = "lead" if kind == "leads" else "call"
        new = [src[h] for h in p["new_" + kind] if h in src]
        chg = [(src[c["hash"]], c["was"]) for c in p["changed_" + kind] if c["hash"] in src]
        cards, ids = [], []
        for r, was in [(r, None) for r in new] + chg:
            uid = ("pl" if kind == "leads" else "pc") + r["hash"]
            ids.append(uid)
            cards.append(row_card(r, k1, uid, was))
        n = len(cards)
        allbtn = (f'<button class="copy solid" type="button" data-target="{" ".join(ids)}">Copy all {n}</button>'
                  if n > 1 else "")
        parts.append(f'<div class="group"><h3>{label} to enter ({E(add)}): {n}</h3>{allbtn}</div>')
        if cards:
            parts.append(f'<ol class="rows">{"".join(cards)}</ol>')
        else:
            parts.append(f'<p class="empty">No new {label.lower()} to enter.</p>')
        wait = [src[h] for h in p["waiting_" + kind] if h in src]
        if wait:
            names = ", ".join(who(r) for r in wait[:12]) + (f" and {len(wait) - 12} more" if len(wait) > 12 else "")
            why = "still inside their text windows" if kind == "leads" else "the call has not happened yet"
            parts.append(f'<p class="waiting">Not finished yet ({why}), so not listed: {E(names)}.</p>')
    return ('<section aria-label="Rows to enter in the portal"><h2>Rows to enter in the portal</h2>'
            + "".join(parts) + "</section>")


def cell(b):
    t = b.get("t")
    small = f"<small>{E(fmt_et(t))}</small>" if t else ""
    return f'<td title="{E(scrub(b["why"]))}"><span class="a {CLS[b["a"]]}">{E(b["a"])}</span>{small}</td>'


def tsv_line(cols):
    return "\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in cols)


def evidence_section(ev):
    leads = sorted(ev["leads"], key=lambda r: r["t0"])
    calls = sorted([c for c in ev["calls"]], key=lambda r: r["start"])
    lh = "".join(f'<th title="{E(label)}">{i + 1}. {E(SHORT[k])}</th>' for i, (k, label) in enumerate(LEAD_BOXES))
    lrows, ltsv = [], [tsv_line(["Lead", "Code", "Lead in (ET)", "Source of time"]
                                + [f"{i + 1}. {label}" for i, (_, label) in enumerate(LEAD_BOXES)]
                                + ["SOP boxes done", "Stage", "Note"])]
    for r in leads:
        note = "duplicate of an earlier lead" if r["duplicate"] else ""
        lrows.append(f'<tr><td>{E(who(r))}</td><td>{E(r["t0_et"])}</td>'
                     + "".join(cell(r["boxes"][k]) for k, _ in LEAD_BOXES)
                     + f'<td>{r["sop_yes"]} of {r["sop_due"]}</td><td>{E(r["stage"] or "")}'
                     + (f"<small>{E(note)}</small>" if note else "") + "</td></tr>")
        ltsv.append(tsv_line([scrub(r["first"]), r["code"], r["t0_et"], r["t0_src"]]
                             + [f"{r['boxes'][k]['a']} ({scrub(r['boxes'][k]['why'])})" for k, _ in LEAD_BOXES]
                             + [f"{r['sop_yes']} of {r['sop_due']}", r["stage"], note]))
    ch = "".join(f'<th title="{E(label)}">{i + 1}. {E(SHORT[k])}</th>' for i, (k, label) in enumerate(CALL_BOXES))
    crows, ctsv = [], [tsv_line(["Lead", "Code", "Call (ET)", "Booked (ET)", "Calendar"]
                                + [f"{i + 1}. {label}" for i, (_, label) in enumerate(CALL_BOXES)]
                                + ["Counts toward the target", "Notes"])]
    for r in calls:
        cnt = "Yes" if r["counts"] else "No"
        crows.append(f'<tr><td>{E(who(r))}</td><td>{E(r["start_et"])}<small>booked {E(r["booked_et"])}</small></td>'
                     + "".join(cell(r["boxes"][k]) for k, _ in CALL_BOXES)
                     + f'<td><span class="a {"y" if r["counts"] else "nd"}">{cnt}</span><small>{E(r["count_why"])}</small></td></tr>')
        ctsv.append(tsv_line([scrub(r["first"]), r["code"], r["start_et"], r["booked_et"], r["calendar"]]
                             + [f"{r['boxes'][k]['a']} ({scrub(r['boxes'][k]['why'])})" for k, _ in CALL_BOXES]
                             + [f"{cnt}: {r['count_why']}", (r.get("notes") or {}).get("text") or ""]))
    out = ['<section aria-label="Evidence"><h2>Evidence for the refund file</h2>',
           '<p class="note">Every lead since ads went live, with every box and its GHL time stamp. Tap a cell on a '
           'computer to see why. Copy a table and paste it into a sheet for the refund file.</p>']
    out.append(f'<div class="group"><h3>Leads: {len(leads)}</h3>'
               f'<button class="copy" type="button" data-target="tsvl">Copy lead table</button></div>')
    if lrows:
        out.append(f'<div class="tablewrap"><table><thead><tr><th>Lead</th><th>Lead in (ET)</th>{lh}'
                   f'<th>SOP</th><th>Stage</th></tr></thead><tbody>{"".join(lrows)}</tbody></table></div>')
    else:
        out.append('<p class="empty">No Lead Suite leads since ads went live.</p>')
    out.append(f'<pre class="tsv" id="tsvl">{E(chr(10).join(ltsv))}</pre>')
    out.append(f'<div class="group"><h3>Booked calls: {len(calls)}</h3>'
               f'<button class="copy" type="button" data-target="tsvc">Copy call table</button></div>')
    if crows:
        out.append(f'<div class="tablewrap"><table><thead><tr><th>Lead</th><th>Call (ET)</th>{ch}'
                   f'<th>Counts</th></tr></thead><tbody>{"".join(crows)}</tbody></table></div>')
    else:
        out.append('<p class="empty">No booked calls from Lead Suite leads yet.</p>')
    out.append(f'<pre class="tsv" id="tsvc">{E(chr(10).join(ctsv))}</pre></section>')
    return "".join(out)


def board_section(ev):
    b, w, s = ev["scoreboard"], ev["window"], ev["sop"]
    pct = min(100, round(100.0 * b["qualified_booked"] / b["target"])) if b["target"] else 0
    live = fmt_day(dt.date.fromisoformat(w["live"]))
    end = fmt_day(dt.date.fromisoformat(w["end"]))
    paused = f", {plural(w['paused_days'], 'paused day')} skipped" if w["paused_days"] else ""

    def rate(x):
        return "none due" if x["pct"] is None else f"{x['pct']}%"

    stats = [
        ("Qualified booked calls", f"{b['qualified_booked']} of {b['target']}",
         f"{b['booked_in_window']} booked in the window, {b['unqualified']} not qualified, {b['cancelled']} canceled"),
        ("Days left", str(max(0, w["left"])), f"{live} to {end}{paused}"),
        ("Showed", str(b["held"]), f"{b['upcoming']} still ahead"),
        ("Lead SOP rate", rate(s["leads"]), f"{s['leads']['yes']} of {s['leads']['yes'] + s['leads']['no']} due boxes"),
        ("Call SOP rate", rate(s["calls"]), f"{s['calls']['yes']} of {s['calls']['yes'] + s['calls']['no']} due boxes"),
        ("Leads since ads live", str(b["leads"]), f"{b['leads_booked']} booked a counted call"),
    ]
    dl = "".join(f"<div><dt>{E(k)}</dt><dd>{E(v)}<small>{E(sm)}</small></dd></div>" for k, v, sm in stats)
    conds = []
    for c in ev.get("conditions") or []:
        lab, cls = PROOF.get(c.get("proof"), ("", "out"))
        live_line = f'<span class="live">{E(c["live"])}</span>' if c.get("live") else ""
        conds.append(f'<li><span class="badge {cls}">{E(lab)}</span><span>{E(c["text"])}</span>'
                     f'<span class="where">{E(c["where"])}</span>{live_line}</li>')
    return (f'<section aria-label="Scoreboard"><h2>Refund scoreboard</h2><div class="card">'
            f'<div class="meter" role="img" aria-label="{b["qualified_booked"]} of {b["target"]} qualified calls">'
            f'<span style="width:{pct}%"></span></div><dl class="stats">{dl}</dl>'
            f'<p class="stand"><strong>Where the refund case stands:</strong> {E(b["line"])}</p>'
            f'<details><summary>Contract conditions: what GHL can prove</summary><ul class="conds">{"".join(conds)}'
            f'</ul></details></div></section>')


def at(s, default):
    """'20:45' -> '8:45pm' for the page."""
    return clock(dt.datetime(2000, 1, 1, *hm(s, default)))


def footer(ev):
    sop = ev["settings_used"]["sop"]
    q = sop.get("quiet_hours") or {}
    q_from, q_to = at(q.get("from"), (20, 45)), at(q.get("to"), (8, 0))
    rules = [
        f"Triple dial: {sop.get('dials_for_triple', 3)} dials within {sop.get('triple_dial_minutes', 5)} min of the "
        f"form fill, or an earlier dial they picked up. A canceled bridge call is not a dial.",
        f"SMS 1: the first text, within {sop.get('sms1_minutes', 5)} min (a late first text is still SMS 1, never "
        f"SMS 2). SMS 2: a later text {sop.get('sms2_hours', [3, 4])[0]} to "
        f"{sop.get('sms2_hours', [3, 4])[1]} hours after the form. SMS 3: a text "
        f"{sop.get('sms3_hours_after_sms2', [2, 3])[0]} to {sop.get('sms3_hours_after_sms2', [2, 3])[1]} hours after SMS "
        f"2. Once they reply, the texts are not due. A STOP reply needs no double dial.",
        f"Double dial: {sop.get('dials_for_double', 2)} dials within {sop.get('double_dial_minutes', 10)} min of their "
        f"first reply, unless they were already talking with us.",
        f"A lead who comes in after {at(sop.get('next_day_after'), (21, 0))} or before {q_to} on their own clock is "
        f"due from {q_to}. Quiet hours are {q_from} to {q_to} on the lead's clock: a text or double dial due then is "
        f"due at {q_to}.",
        "An answered call with no length in GHL counts as a talk, but the box says Check: it may have been a voicemail.",
        "Triage: an answered call of a minute or more before the meeting. Pre-call email: sent the evening before "
        f"(from {at(sop.get('evening_from'), (17, 0))}). Morning confirm: a call or text the morning of the call, from "
        f"{at(sop.get('morning_from'), (5, 0))} until {at(sop.get('morning_until'), (12, 0))} or the call, whichever is "
        "first. Show-rate SOP: the booking confirmation, the pre-call email and the morning confirm.",
        "A filled STL field in GHL wins over the message times. When they disagree the row says Check.",
        "A booked call counts when it was booked inside the window" if ev["settings_used"]["count_rule"] == "booked_at"
        else "A booked call counts when it happens inside the window",
    ]
    rules[-1] += (", it was not canceled, and GHL does not mark the lead unqualified (stage or STL Outcome Reason). "
                  "A person who filled the form twice is one lead. Lead replied and Showed are outcomes, so they are "
                  "left out of the SOP rate.")
    fr = ev["field_report"]
    facts = [f"STL fields found in GHL: {len(fr['found'])} of {len(fr['found']) + len(fr['missing'])}. "
             f"{fr['leads_with_any']} of {plural(fr['leads'], 'lead')} have any box field filled; the rest of the "
             "answers come from GHL message time stamps."]
    x = ev["excluded"]
    left_out = [plural(x[k], lab) for k, lab in (("test", "test contact"), ("duplicate", "duplicate lead"),
                                                 ("before_live", "contact from before ads went live")) if x.get(k)]
    if left_out:
        facts.append("Left out of the SOP rate: " + ", ".join(left_out) + ".")
    bound = [e[1] for e in ev.get("errors") or [] if e and e[0] == "bound"]
    other = [e for e in ev.get("errors") or [] if e and e[0] != "bound"]
    if bound:
        facts.append("Read limit hit: " + "; ".join(bound) + ".")
    if other:
        facts.append(f"{plural(len(other), 'GHL read')} failed this run. Boxes that needed them say Unknown.")
    facts.append("This page only reads GHL. It never writes, tags or texts. First names and reply codes only.")
    return (f'<footer><details><summary>How each box is judged</summary><ul>'
            + "".join(f"<li>{E(r)}</li>" for r in rules) + "</ul></details>"
            + "".join(f"<div>{E(f)}</div>" for f in facts) + "</footer>")


def top_line(ev):
    b, w = ev["scoreboard"], ev["window"]
    rows = sum(len(ev["portal"][k]) for k in ("new_leads", "changed_leads", "new_calls", "changed_calls"))
    days = f"{plural(max(0, w['left']), 'day')} left" if not w["over"] else "window closed"
    return f"{b['qualified_booked']} of {b['target']} qualified calls, {days}, {plural(rows, 'portal row')} to enter"


def render(ev):
    loc = ev.get("location_key") or "hq"
    eyebrow = "Lead Suite evidence" if loc == "hq" else f"Test run on {E(loc.upper())} data"
    fatal = (f'<p class="empty"><strong>{E(ev["fatal"])}</strong></p>' if ev.get("fatal") else "")
    state = json.dumps(ev.get("state") or {}, separators=(",", ":")).replace("</", "<\\/")
    return (
        '<title>Lead Suite Evidence</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
        f"<style>{CSS}</style>\n"
        f'<main class="wrap"><header><div class="eyebrow">{eyebrow}</div><h1>{E(top_line(ev))}</h1>'
        f'<p class="stamp">Last updated {E(ev.get("generated_et") or "")} ET</p></header>{fatal}'
        f"{board_section(ev)}{portal_section(ev)}{evidence_section(ev)}{footer(ev)}</main>\n"
        f'<script type="application/json" id="ls-state">{state}</script>\n'
        f"<script>{JS}</script>\n"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the Lead Suite evidence page.")
    ap.add_argument("--evidence", default=os.path.join(prof.OUT_DIR, "evidence.json"))
    ap.add_argument("--out", default=os.path.join(prof.OUT_DIR, "ls_evidence.html"))
    a = ap.parse_args(argv)
    with open(a.evidence, encoding="utf-8") as f:
        ev = json.load(f)
    page = render(ev)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"page: {len(page)} bytes -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
