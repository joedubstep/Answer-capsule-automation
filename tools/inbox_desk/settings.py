"""Rules and settings for the Inbox Desk.

Three layers, merged in this order:
1. tools/inbox_desk/senders.json: public sender rules (business domains, subjects, campaign wording).
2. config/surven.json: the cold email domains, Joey's Gmail, Notion ids, and an optional "inbox_desk" block
   filled at deploy ({"booking_link": "...", "client_domains": {"legacy": ["..."]}}).
3. A private file written at run time from the Notion page config notion.inbox_desk_settings. It holds the
   people who write from a personal address (a coach on Gmail, a client's own address, Joey's other inboxes).
   Those never go in this public repo.

The Notion page is plain lines, one per sender (bullets are fine):
    own: <address>
    client agc: <address or domain>
    coach <Name>: <address or domain>
    vendor <Name>: <address or domain>
    ignore: <address or domain>
Notion shows each address as a mailto link ([a@example.com](mailto:a@example.com)); links and mailto: are
stripped and each (kind, label, address) is kept once.

  python3 -m tools.inbox_desk.settings --from-text /tmp/inbox_desk/settings.md --out /tmp/inbox_desk/private.json
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SENDERS = os.path.join(HERE, "senders.json")
CONFIG = os.path.join(REPO, "config", "surven.json")
OUT_DIR = os.environ.get("INBOX_DESK_DIR", "/tmp/inbox_desk")
PRIVATE = os.path.join(OUT_DIR, "private.json")

_LINE = re.compile(r"^\s*(?:[-*\u2022]\s*)?(?:\[[ x]\]\s*)?(own|client|coach|vendor|ignore)\b\s*([^:]*?)\s*:\s*(.+?)\s*$",
                   re.I)
_ADDR = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+|(?<![@\w])(?:[\w-]+\.)+[a-z]{2,}(?![\w@])", re.I)
# Notion stores an address as a mailto link: [a@example.com](mailto:a@example.com) or <mailto:a@example.com>.
# Read each link once.
_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*<?([^)\s>]*)>?\s*\)")
_AUTOLINK = re.compile(r"<\s*((?:mailto:|https?://)?[^<>\s]+)\s*>", re.I)
_SCHEME = re.compile(r"\b(?:mailto:|https?://)", re.I)


def _link_text(m):
    """A markdown link -> its visible text, or the target when the text holds no address."""
    text, target = m.group(1), m.group(2)
    return text if _ADDR.search(text) else target


def clean_line(raw):
    """One page line -> plain text: markdown links and mailto: dropped, markdown marks removed. Underscores inside
    a word (first_last@example.com) and escaped ones (first\\_last) stay part of the address."""
    line = re.sub(r"\\([\\`*_\[\]()<>#.!-])", r"\1", raw)
    line = _MD_LINK.sub(_link_text, line)
    line = _AUTOLINK.sub(r"\1", line)
    line = _SCHEME.sub("", line)
    line = re.sub(r"[`*]", "", line)
    return re.sub(r"(?<![\w.+-])_+|_+(?![\w@.-])", "", line)


def _add(lst, vals):
    """Append each value once, in order (a link repeats the address it shows)."""
    for v in vals:
        if v not in lst:
            lst.append(v)


def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "other"


def parse_settings_text(text):
    """The private Notion page text -> {"own": [...], "clients": {...}, "coaches": {...}, "vendors": {...}, "ignore": [...]}."""
    out = {"own": [], "clients": {}, "coaches": {}, "vendors": {}, "ignore": []}
    for raw in (text or "").splitlines():
        m = _LINE.match(clean_line(raw))
        if not m:
            continue
        kind, name, rest = m.group(1).lower(), m.group(2).strip(), m.group(3)
        vals = [v.lower().strip(".") for v in _ADDR.findall(rest)]
        if not vals:
            continue
        if kind in ("own", "ignore"):
            _add(out[kind], vals)
            continue
        group = {"client": "clients", "coach": "coaches", "vendor": "vendors"}[kind]
        key = slug(name) if name else "other"
        ent = out[group].setdefault(key, {"label": name or key, "senders": []})
        _add(ent["senders"], vals)
    return out


def load_rules(private=None, config=None, senders=None):
    """One merged dict the classifier reads. private: dict or a path (missing file is fine)."""
    rules = json.loads(json.dumps(senders if senders is not None else _load(SENDERS, {})))
    cfg = config if config is not None else _load(CONFIG, {})
    if isinstance(private, str):
        private = _load(private, {})
    private = private or {}
    desk_cfg = cfg.get("inbox_desk") or {}

    joey = ((cfg.get("google") or {}).get("joey_gmail") or "").lower()
    cold = [d.lower() for d in (cfg.get("cold_email_domains") or [])]
    shared = [d.lower() for d in (rules.get("campaign", {}).get("shared_domains") or [])]
    rules["joey_gmail"] = joey
    rules["cold_domains"] = cold
    rules["cold_only_domains"] = [d for d in cold if d not in shared]
    rules["own_addresses"] = sorted({a for a in ([joey] + list(private.get("own") or [])) if a})
    rules["own_domains"] = sorted(set(cold) | set(shared))
    rules["ignore"] = list(private.get("ignore") or [])
    rules["booking_link"] = desk_cfg.get("booking_link") or (cfg.get("campaign") or {}).get("booking_link") or ""
    rules["notion"] = cfg.get("notion") or {}

    # clients: public domains + deploy-time config domains + private senders
    clients = rules.setdefault("clients", {})
    for key, doms in (desk_cfg.get("client_domains") or {}).items():
        ent = clients.setdefault(key, {"label": key, "domains": [], "relay_domains": []})
        ent["domains"] = sorted(set(ent.get("domains") or []) | {d.lower() for d in doms})
    for group in ("clients", "coaches", "vendors"):
        target = rules.setdefault(group, {})
        for key, ent in (private.get(group) or {}).items():
            cur = target.setdefault(key, {"label": ent.get("label") or key, "domains": []})
            cur.setdefault("senders", [])
            for v in ent.get("senders") or []:
                _add(cur["senders"] if "@" in v else cur["domains"], [v])
    return rules


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from-text", required=True, help="the settings page text, saved to a file")
    ap.add_argument("--out", default=PRIVATE)
    a = ap.parse_args(argv)
    with open(a.from_text, encoding="utf-8") as f:
        data = parse_settings_text(f.read())
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    n = len(data["own"]) + len(data["ignore"]) + sum(len(e["senders"]) for g in ("clients", "coaches", "vendors")
                                                    for e in data[g].values())
    # counts only: never print the addresses themselves
    print(f"settings: {n} sender(s): {len(data['clients'])} client group(s), {len(data['coaches'])} coach(es), "
          f"{len(data['vendors'])} vendor(s), {len(data['own'])} own, {len(data['ignore'])} ignored -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
