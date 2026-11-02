"""The one-page plan a home asked for: HTML in Surven's brand, then a PDF to attach to the reply draft.

  python3 -m tools.inbox_desk.plan --facts /tmp/inbox_desk/plans/<thread>.json [--out-dir DIR]
                                   [--engine auto|chrome|mini|html] [--max-kb 40] [--booking-link URL]

facts.json (written by the model, from what the home wrote and pages it opened):
  {"home": "Example Gardens", "city": "Springfield", "state": "OH",
   "beds": {"value": 48, "source": "https://<state license record or the home's own site>"},
   "care_type": {"value": "Assisted living and memory care", "source": "https://..."}}

Rules enforced here, not left to the model:
  - beds and care type print only with a source link, and only from a state record (.gov / .us) or the home's
    own site. Directory and listing sites (Caring, A Place for Mom, Yelp, Facebook, Google...) are dropped.
  - the 3 steps, the try-this-week line and the ask come from plan_steps.json (the offer), never from the model.
  - no price, no stats, no promises: the whole visible text passes the copy checker as prospect_email with the
    booking link required. Exit 1 when it does not.
Engines: chrome (node + playwright, the prettiest) when it is installed and the PDF is under --max-kb, else mini
(tools/inbox_desk/minipdf.py, about 3 KB, safe to pass to the Gmail connector as base64), else html.
Writes plan.html, plan.pdf, plan.b64 (the attachment as base64), plan.txt (the visible words) and meta.json.
Exit 0 ok, 1 copy check blocked, 2 bad facts.
"""
import argparse
import base64
import datetime as _dt
import html
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import urllib.parse

from shared import et
from tools.inbox_desk import minipdf
from tools.inbox_desk import settings as st

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "plan_template.html")
STEPS = os.path.join(HERE, "plan_steps.json")
PLANS_DIR = os.path.join(st.OUT_DIR, "plans")

DIRECTORIES = ("caring.com", "aplaceformom.com", "seniorly.com", "senioradvisor.com", "seniorhomes.com",
               "memorycare.com", "assistedliving.org", "seniorliving.org", "theseniorlist.com", "agingcare.com",
               "payingforseniorcare.com", "yelp.com", "facebook.com", "google.com", "goo.gl", "bbb.org",
               "yellowpages.com", "mapquest.com", "linkedin.com", "instagram.com", "seniorcare.com",
               "retirementliving.com", "assistedlivingfacilities.org", "seniorguidance.org", "brookdale.com",
               "carelistings.com", "familyassets.com", "medicare.gov", "cms.gov")  # federal sites are not state records
BRAND = {"cream": "#f2eee3", "paper": "#faf7ef", "sage": "#4e6242", "ink": "#181b18", "hair": "#c8c1b1",
         "muted": "#5b5f57"}
STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
             "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
STATE_US = re.compile(r"\.(?:state\.)?(?:%s)\.us$" % "|".join(sorted(s.lower() for s in STATES)))


# ---------------------------------------------------------------- facts

def source_kind(url):
    """'state license record' | "the home's own website" | None (not allowed)."""
    try:
        u = urllib.parse.urlparse((url or "").strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    host = u.netloc.lower().split("@")[-1].split(":")[0]
    bare = host[4:] if host.startswith("www.") else host
    full = bare + u.path.lower()
    if any(bare == d or bare.endswith("." + d) or full.startswith(d) for d in DIRECTORIES):
        return None
    # a state record: a .gov site, or a state government .us site (dhs.state.mn.us, apps.example.tx.us).
    # A home's own site on .us (maplehome.us) is the home's own website, not a state record.
    if bare.endswith(".gov") or STATE_US.search(bare):
        return "state license record"
    return "the home's own website"


def clean_text(s, limit=80):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    s = s.replace("\u2014", ", ").replace("\u2013", " to ")
    return s[:limit].strip()


def verified_facts(facts):
    """(facts to print, dropped [(name, why)])."""
    out, dropped = {}, []
    home = clean_text(facts.get("home"), 80)
    if not home:
        raise ValueError("facts.home is required")
    out["home"] = home
    city = clean_text(facts.get("city"), 40)
    state = clean_text(facts.get("state"), 20)
    if state.upper() in STATES:
        state = state.upper()
    out["city"], out["state"] = city, state
    for key, label in (("beds", "Licensed beds"), ("care_type", "Care type")):
        f = facts.get(key)
        if f in (None, "", {}):
            continue
        if not isinstance(f, dict):
            dropped.append((key, "no source link"))
            continue
        val, src = f.get("value"), (f.get("source") or "").strip()
        kind = source_kind(src)
        if not src:
            dropped.append((key, "no source link"))
            continue
        if not kind:
            dropped.append((key, "source is not a state record or the home's own site"))
            continue
        if key == "beds":
            try:
                val = int(str(val).strip())
            except ValueError:
                dropped.append((key, "not a number"))
                continue
            if not 1 <= val <= 1500:
                dropped.append((key, "not a believable bed count"))
                continue
        else:
            val = clean_text(val, 80)
            if not val:
                dropped.append((key, "empty"))
                continue
        out[key] = {"label": label, "value": val, "source": src, "kind": kind,
                    "host": urllib.parse.urlparse(src).netloc.lower().replace("www.", "")}
    return out, dropped


# ---------------------------------------------------------------- words

def load_steps(path=STEPS):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def words(f, steps, booking_link, date_label):
    place = f["city"] or "you"
    fill = lambda s: (s or "").replace("{home}", f["home"]).replace("{place}", place) \
        .replace("{booking_link}", booking_link)  # noqa: E731
    where = ", ".join(x for x in (f["city"], f["state"]) if x)
    w = {
        "title": fill(steps["title"]),
        "sub": ((where + ". ") if where else "") + "Prepared " + date_label + ".",
        "intro": fill(steps["intro"]),
        "facts": [(f[k]["label"], str(f[k]["value"]), f[k]["kind"], f[k]["host"], f[k]["source"])
                  for k in ("beds", "care_type") if k in f],
        "steps": [(fill(s["title"]), fill(s["text"])) for s in steps["steps"]],
        "timeline": fill(steps["timeline"]),
        "try_title": fill(steps["try_title"]),
        "try": fill(steps["try_this_week"]),
        "ask": fill(steps["ask"]),
        "book": fill(steps["book_line"]),
        "link": booking_link,
        "sign": fill(steps["sign"]),
        "note": fill(steps["facts_note"]) if any(k in f for k in ("beds", "care_type")) else "",
    }
    return w


def visible_text(w):
    lines = [w["title"] + ".", w["sub"], "", w["intro"], ""]
    for label, val, kind, host, _src in w["facts"]:
        lines.append(f"{label}: {val}. Source: {kind}.")
    if w["facts"]:
        lines.append("")
    for i, (t, x) in enumerate(w["steps"], 1):
        lines += [f"{t}.", x, ""]
    lines += [w["timeline"], "", w["try_title"] + ".", w["try"], "", w["ask"], w["book"], "", w["sign"]]
    if w["note"]:
        lines += ["", w["note"]]
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------- HTML

def render_html(w, for_print=False):
    e = lambda s: html.escape(s or "", quote=True)  # noqa: E731
    facts = ""
    if w["facts"]:
        rows = "".join(
            f'<tr><td class="k">{e(label)}</td><td>{e(val)}<br><span class="src">Source: '
            f'<a href="{e(src)}">{e(kind)} ({e(host)})</a></span></td></tr>'
            for label, val, kind, host, src in w["facts"])
        facts = f'<h2>Your home</h2><table class="facts">{rows}</table>'
    steps = "\n      ".join(f"<li><b>{e(t)}</b>{e(x)}</li>" for t, x in w["steps"])
    link = e(w["link"])
    book = e(w["book"]).replace(link, f'<a href="{link}">{link}</a>') if link else e(w["book"])
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = string.Template(fh.read())
    out = tpl.safe_substitute(
        title_text=e(w["title"]), title_html=e(w["title"]), sub_html=e(w["sub"]), intro_html=e(w["intro"]),
        facts_html=facts, steps_html=steps, timeline_html=e(w["timeline"]), try_title_html=e(w["try_title"]),
        try_html=e(w["try"]), ask_html=e(w["ask"]), book_html=book, sign_html=e(w["sign"]), footer_html=e(w["note"]))
    if for_print:
        out = out.replace('<html lang="en">', '<html lang="en" data-print>', 1)
    return out


# ---------------------------------------------------------------- PDF engines

def mini_pdf(w):
    """One Letter page drawn with minipdf. Shrinks the type a little if the words would run off the page."""
    for scale in (1.0, 0.94, 0.88, 0.82):
        p = minipdf.Page()
        y = _layout(p, w, scale)
        if y <= 772:
            break
    return minipdf.build(p, title=w["title"], author="Surven")


def _layout(p, w, s):
    B = BRAND
    L, R = 44, 568
    width = R - L
    p.rect(0, 0, 612, 792, B["paper"])
    title_lines = minipdf.wrap(w["title"], 20 * s, width, bold=True)
    head_h = 58 + 25 * s * len(title_lines) + 24
    p.rect(0, 0, 612, head_h, B["sage"])
    p.text(L, 34, "SURVEN", 9, True, B["cream"])
    y = 62
    for ln in title_lines:
        p.text(L, y, ln, 20 * s, True, B["cream"])
        y += 25 * s
    p.text(L, y + 4, w["sub"], 10.5 * s, False, B["cream"])
    y = head_h + 30 * s
    y = p.para(L, y, w["intro"], 11 * s, width)

    def heading(y, text):
        y += 12 * s
        p.text(L, y, text.upper(), 9.5 * s, True, B["sage"])
        p.line(L, y + 5, R, y + 5, B["hair"])
        return y + 22 * s

    if w["facts"]:
        y = heading(y, "Your home")
        for label, val, kind, host, src in w["facts"]:
            p.text(L, y, label, 11 * s, False, B["muted"])
            p.text(L + 120, y, val, 11 * s, True, B["ink"])
            y += 13 * s
            src_txt = "Source: %s (%s)" % (kind, host)
            p.text(L + 120, y, src_txt, 8.5 * s, False, B["sage"])
            p.link(L + 120, y - 9 * s, minipdf.width(src_txt, 8.5 * s), 11 * s, src)
            y += 17 * s
    y = heading(y, "What we would set up in your first 90 days")
    for i, (t, x) in enumerate(w["steps"], 1):
        box = 17 * s
        p.rect(L, y - 12.5 * s, box, box, B["sage"])
        num = str(i)
        p.text(L + (box - minipdf.width(num, 10 * s, True)) / 2, y, num, 10 * s, True, B["cream"])
        p.text(L + 28, y, t, 11.5 * s, True, B["ink"])
        y = p.para(L + 28, y + 15 * s, x, 10.5 * s, width - 28)
        y += 6 * s
    y = p.para(L, y, w["timeline"], 9.5 * s, width, color=B["muted"])
    y = heading(y, w["try_title"]) + 6 * s
    try_lines = minipdf.wrap(w["try"], 10.5 * s, width - 24)
    top = y - 18 * s
    box_h = 14 * s * len(try_lines) + 20 * s
    p.rect(L, top, width, box_h, B["cream"])
    for x1, y1, x2, y2 in ((L, top, R, top), (L, top + box_h, R, top + box_h), (L, top, L, top + box_h),
                           (R, top, R, top + box_h)):
        p.line(x1, y1, x2, y2, B["hair"])
    yy = y
    for ln in try_lines:
        p.text(L + 12, yy, ln, 10.5 * s, False, B["ink"])
        yy += 14 * s
    y = top + box_h + 22 * s
    p.line(L, y, R, y, B["hair"])
    y += 22 * s
    p.text(L, y, w["ask"], 13 * s, True, B["ink"])
    y += 18 * s
    lead = w["book"].replace(w["link"], "").rstrip()
    p.text(L, y, lead, 10.5 * s, False, B["ink"])
    lx = L + minipdf.width(lead + " ", 10.5 * s)
    link_lines = minipdf.wrap(w["link"], 10.5 * s, R - lx, bold=True) if w["link"] else []
    for ln in link_lines[:2]:
        p.text(lx, y, ln, 10.5 * s, True, B["sage"])
        p.link(lx, y - 10 * s, minipdf.width(ln, 10.5 * s, True), 13 * s, w["link"])
        y += 14 * s
    y += 6 * s
    p.text(L, y, w["sign"], 10 * s, False, B["muted"])
    if w["note"]:
        p.text(L, 772, w["note"], 8.5 * s, False, B["muted"])
    return y


def npm_root():
    for cand in (os.environ.get("NODE_PATH", ""), "/opt/node22/lib/node_modules", "/usr/lib/node_modules",
                 "/usr/local/lib/node_modules"):
        for c in cand.split(os.pathsep):
            if c and os.path.isdir(os.path.join(c, "playwright")):
                return c
    try:
        r = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=20)
        c = r.stdout.strip()
        return c if c and os.path.isdir(os.path.join(c, "playwright")) else ""
    except Exception:  # noqa: BLE001
        return ""


_NODE = """const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + process.argv[2]);
  await p.pdf({ path: process.argv[3], format: 'Letter', printBackground: true, preferCSSPageSize: true });
  await b.close();
})().catch(e => { console.error(String(e).slice(0, 300)); process.exit(1); });
"""


def chrome_pdf(html_path, pdf_path, timeout=90):
    """(ok, note). Needs node and playwright with its browser installed."""
    if not shutil.which("node"):
        return False, "node not found"
    root = npm_root()
    if not root:
        return False, "playwright not installed"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_NODE)
        js = f.name
    try:
        env = dict(os.environ, NODE_PATH=root)
        r = subprocess.run(["node", js, os.path.abspath(html_path), os.path.abspath(pdf_path)], capture_output=True,
                           text=True, timeout=timeout, env=env)
        if r.returncode != 0 or not os.path.exists(pdf_path):
            return False, "chrome failed: " + (r.stderr or r.stdout).strip().splitlines()[-1][:160] if (r.stderr or r.stdout) else "chrome failed"
        return True, "chrome"
    except subprocess.TimeoutExpired:
        return False, "chrome timed out"
    finally:
        os.unlink(js)


# ---------------------------------------------------------------- main

def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:60] or "home"


def render(facts, out_dir, engine="auto", max_kb=40, booking_link=None, today=None):
    rules = st.load_rules(private={})
    link = booking_link if booking_link is not None else rules.get("booking_link", "")
    f, dropped = verified_facts(facts)
    steps = load_steps()
    d = today or et.now_et().date()
    if isinstance(d, str):
        d = _dt.date.fromisoformat(d[:10])
    date_label = d.strftime("%B ") + str(d.day) + d.strftime(", %Y")
    w = words(f, steps, link, date_label)
    os.makedirs(out_dir, exist_ok=True)
    text = visible_text(w)
    with open(os.path.join(out_dir, "plan.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    from tools.inbox_desk.drafts import check
    chk = check(text, "prospect_email", require_link=True)
    html_path = os.path.join(out_dir, "plan.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(w))
    pdf_path = os.path.join(out_dir, "plan.pdf")
    notes, used = [], None
    if engine in ("auto", "chrome"):
        print_html = os.path.join(out_dir, "plan_print.html")
        with open(print_html, "w", encoding="utf-8") as fh:
            fh.write(render_html(w, for_print=True))
        ok, note = chrome_pdf(print_html, pdf_path)
        os.unlink(print_html)
        if ok:
            kb = os.path.getsize(pdf_path) / 1024.0
            if engine == "chrome" or kb <= max_kb:
                used = "chrome"
            else:
                notes.append("chrome PDF was %.0f KB, over %d KB, so the small PDF is attached" % (kb, max_kb))
        else:
            notes.append(note)
    if used is None and engine in ("auto", "mini"):
        with open(pdf_path, "wb") as fh:
            fh.write(mini_pdf(w))
        used = "mini"
    if used is None:
        used = "html"
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)
    attach = pdf_path if used in ("chrome", "mini") else html_path
    with open(attach, "rb") as fh:
        raw = fh.read()
    b64 = base64.b64encode(raw).decode("ascii")
    with open(os.path.join(out_dir, "plan.b64"), "w", encoding="ascii") as fh:
        fh.write(b64)
    meta = {"home": f["home"], "engine": used, "notes": notes,
            "filename": f"{f['home']} plan." + ("pdf" if used != "html" else "html"),
            "mime": "application/pdf" if used != "html" else "text/html",
            "attachment": attach, "b64_file": os.path.join(out_dir, "plan.b64"), "bytes": len(raw),
            "b64_chars": len(b64), "facts_printed": [k for k in ("beds", "care_type") if k in f],
            "dropped": [{"fact": k, "why": why} for k, why in dropped], "booking_link_set": bool(link),
            "copy": chk}
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the one-page plan (HTML and PDF).")
    ap.add_argument("--facts", required=True)
    ap.add_argument("--out-dir")
    ap.add_argument("--engine", default="auto", choices=("auto", "chrome", "mini", "html"))
    ap.add_argument("--max-kb", type=int, default=40)
    ap.add_argument("--booking-link")
    ap.add_argument("--date", help="YYYY-MM-DD shown on the plan (default: today, Eastern)")
    a = ap.parse_args(argv)
    try:
        with open(a.facts, encoding="utf-8") as fh:
            facts = json.load(fh)
        out_dir = a.out_dir or os.path.join(PLANS_DIR, slug(facts.get("home")))
        meta = render(facts, out_dir, a.engine, a.max_kb, a.booking_link, a.date)
    except (OSError, ValueError) as e:
        print(f"plan: bad facts: {e}")
        return 2
    c = meta["copy"]
    print(f"plan: {meta['home']}: {meta['engine']} {meta['bytes']} bytes, base64 {meta['b64_chars']} chars, "
          f"facts {', '.join(meta['facts_printed']) or 'none'}"
          + (f", dropped {', '.join(d['fact'] + ' (' + d['why'] + ')' for d in meta['dropped'])}" if meta['dropped'] else "")
          + f", copy {'ok' if c['ok'] else 'BLOCKED'}" + (f" ({len(c['warnings'])} warning(s))" if c['warnings'] else "")
          + f" -> {out_dir}")
    for n in meta["notes"]:
        print("  note: " + n)
    if not c["ok"]:
        for b in c["blocking"]:
            print(f"  BLOCK {b['rule']}: {b['match']!r} -> {b['fix']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
