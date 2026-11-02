"""Shared helpers for the Time Ledger: config, work folder, text cleanup, tokens, keys, clock formatting.

Nothing here touches the network. The work folder is /tmp/time_ledger unless TIME_LEDGER_DIR says otherwise
(tests point it at a temp folder).
"""
import datetime as dt
import hashlib
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(ROOT, "config", "surven.json")
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "model.json")

ROLES = ["CEO", "Sales", "Offer work", "Marketing", "Client delivery", "CTO", "Business development", "Admin",
         "Billing and finance", "HR and hiring", "Personal"]
NOT_LOGGED = "Not logged"
KINDS = ["Outreach", "Selling", "Client work", "Offer", "Learning", "Personal", "Distraction", "Tools", "Planning",
         "Data sale", "Marketing", "Admin", "SOPs", "Fixes", "Other"]
BREAK_TASK = "Break"
BLANK_TEXT = "(blank block)"


def work_dir():
    d = os.environ.get("TIME_LEDGER_DIR") or "/tmp/time_ledger"
    os.makedirs(d, exist_ok=True)
    return d


def wpath(name):
    return os.path.join(work_dir(), name)


def load_config(path=None):
    try:
        with open(path or CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")


def write_text(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- text

_MD_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_TAG = re.compile(r"<[^>]+>")
_ESC = re.compile(r"\\([\\`*_{}\[\]()#+\-.!$|>~])")


def clean(s):
    """Notion-flavored markdown fragment -> plain one-line text."""
    if not s:
        return ""
    s = _MD_LINK.sub(r"\1", s)
    s = _TAG.sub(" ", s)
    s = _ESC.sub(r"\1", s)
    s = html.unescape(s)
    s = s.replace(" ", " ").replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


STOP = set("""a an the and or but if then so of to in on at by for with from up down out over into onto about as is are
was were be been being am do does did doing done have has had having it its this that these those there here i me my
we our you your he she they them their his her him what which who whom whose when where why how all any both each few
more most other some such no nor not only own same than too very can will just should now also like okay ok um uh yeah
get got gets getting go going went make made making quick quickly little bit lot really actually basically""".split())


_DOUBLE = re.compile(r"([bgmnpt])\1$")


def stem(w):
    """Tiny suffix stripper (enough to make 'calls', 'calling' and 'called' one feature)."""
    if len(w) <= 3 or w.isdigit():
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            base = w[: -len(suf)]
            return base[:-1] if _DOUBLE.search(base) else base
    if re.search(r"(sh|ch|x|z|ss|us)es$", w):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    if w.endswith("ly") and len(w) > 5:
        return w[:-2]
    return w


def tokens(text, keep_stop=False):
    """Lowercase word tokens with digits-only words dropped and a light stem."""
    t = clean(text).lower().replace("'s ", " ").replace("’s ", " ")
    t = re.sub(r"\bwi-?fi\b", "wifi", t)
    t = re.sub(r"\bfollow-?ups?\b", "followup", t)
    t = re.sub(r"\bto-?dos?\b", "todo", t)
    out = []
    for w in re.findall(r"[a-z][a-z0-9]*|\d+[a-z]+[a-z0-9]*", t):
        if not keep_stop and w in STOP:
            continue
        out.append(stem(w))
    return out


def norm_for_key(text):
    return re.sub(r"\s+", " ", clean(text).lower()).strip()


def row_key(log_date, block_start, position, text):
    """Stable id of one action: hash of log date + block start + position + text."""
    raw = "tl1|%s|%s|%s|%s" % (log_date, block_start or "", position, norm_for_key(text))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------- clock

def fmt_clock(minutes):
    """Minutes since the log day's midnight (may pass 1440 after midnight) -> '7:59 am'."""
    if minutes is None:
        return ""
    m = int(round(minutes)) % 1440
    h, mm = divmod(m, 60)
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return "%d:%02d %s" % (h12, mm, ap)


def fmt_hhmm(minutes):
    if minutes is None:
        return None
    m = int(round(minutes))
    return "%02d:%02d" % divmod(m, 60)


def parse_day(s):
    return dt.date.fromisoformat(str(s)[:10])


def md_label(d):
    """date -> 'Nov 2'."""
    return "%s %d" % (d.strftime("%b"), d.day)


def hours(mins):
    mins = float(mins or 0)
    if mins < 60:
        return "%d min" % round(mins)
    return "%.1f h" % (mins / 60.0)
