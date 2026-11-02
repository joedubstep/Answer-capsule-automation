"""Text helpers: what a person actually wrote, their sign-off, and a few facts pulled from it.

The quote cutting is ported from surven-carehome surven_outreach/reply_text.py (new_text, is_opt_out), which the
cold email engine uses on the same replies, plus two cases seen in Joey's Gmail on 2026-11-02:
  - Outlook replies relayed through GoHighLevel put "-----Original Message----- From: ... Sent: ..." in the
    middle of a line, so the cut also works inline;
  - security banners (Proofpoint, Check Point) sit inside the quoted original and must not count as their words.
Signatures and legal notices are split off so a home name in a signature never reads as the reply itself.
"""
import html
import re

_CUT = [
    re.compile(r"^\s*-{2,}\s*original message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*forwarded message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*_{8,}\s*$"),
    re.compile(r"^\s*from:\s.+", re.I),
    re.compile(r"^\s*on\s.+\bwrote:\s*$", re.I),
    re.compile(r"^\s*>"),
]
_ON_START = re.compile(r"^\s*on\s.+", re.I)
_INLINE_CUT = [
    re.compile(r"-{3,}\s*original message\s*-{3,}", re.I),
    re.compile(r"\bfrom:\s[^\n]{0,200}?\bsent:\s", re.I),
]
_LEGAL = re.compile(r"\b(?:confidential(?:ity)?|privileged|intended (?:only|solely) for|this (?:e-?mail|message|"
                    r"transmission) and any attachments|if you (?:have )?received this (?:e-?mail|message|"
                    r"communication) in error|disclaimer)\b", re.I)
_CLOSING = re.compile(r"^\s*(?:thanks|thank you|many thanks|thanks again|best|best regards|regards|kind regards|"
                      r"warm regards|warmly|sincerely|respectfully|cheers|take care|blessings|have a (?:great|good) "
                      r"(?:day|one))\s*[,.!]?\s*$", re.I)
_SENT_FROM = re.compile(r"^\s*sent from my\b", re.I)
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_URL = re.compile(r"https?://\S+|<https?://[^>]+>")
_NAME_LINE = re.compile(r"^\s*\*?([A-Z][a-zA-Z'.-]+(?:\s+[A-Z][a-zA-Z'.-]+){0,3})\*?\s*,?\s*(?:[A-Z]{2,6}(?:[-,/ ]+[A-Z]{2,6})*)?\s*$")
_NOT_NAMES = {"the", "our", "thank", "thanks", "best", "office", "cell", "fax", "email", "lic", "sent", "assisted",
              "senior", "home", "administrator", "director", "owner", "manager", "executive", "regards", "sincerely",
              "main", "mobile", "phone", "tel", "website", "www", "confidential", "joey", "hello", "hi", "hey",
              "yes", "no", "community", "memory", "care", "living", "residential", "leasing", "sales"}
_WORD_NUM = {"zero": 0, "none": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "a few": 3, "several": 3}

# Opt-out (ported from reply_text.is_opt_out, 10/28 version). "not interested" is left out on purpose: the desk
# reads it as not_interested_or_full, which also gets no draft.
_OPT_PHRASES = re.compile(r"\b(unsubscribe|remove (me|us)|take (me|us) off|(off|from) (your|the) "
                          r"(e-?mail(ing)?|mailing|contact) list|stop (e-?mailing|emailing|contacting|sending)|"
                          r"(do not|don'?t) (e-?mail|contact)|no more e-?mails?)\b", re.I)
_OPT_FIRST = re.compile(r"^(please\s+)?(no|stop|unsubscribe|remove)\b(?!\s+(longer|problem|worries)\b)", re.I)
_ROOM_WORDS = re.compile(r"\b(rooms?|beds?|availab\w*|vacanc\w*|openings?|open|full|units?|spots?|census)\b", re.I)


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", s or "")
    s = re.sub(r"(?is)<blockquote\b.*", "", s)
    s = re.sub(r"(?is)<div[^>]*class=\"[^\"]*gmail_quote[^\"]*\".*", "", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    return html.unescape(s).replace("\xa0", " ")


def body_of(msg):
    """Plain text of one Gmail MCP message dict (plaintextBody, else htmlBody as text, else snippet)."""
    t = msg.get("plaintextBody") or msg.get("plaintext_body") or ""
    if not t.strip():
        h = msg.get("htmlBody") or msg.get("html_body") or ""
        t = html_to_text(h) if h else html.unescape(msg.get("snippet") or "")
    return t.replace("\r\n", "\n").replace("\r", "\n")


def split_reply(text):
    """(new, quoted): what they wrote this time, and the quoted original under it."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for rx in _INLINE_CUT:
        m = rx.search(text)
        if m and m.start() > 0:
            text = text[:m.start()] + "\n" + text[m.start():]
    lines = text.split("\n")
    cut = len(lines)
    for i, line in enumerate(lines):
        if any(p.match(line) for p in _CUT):
            cut = i
            break
        if _ON_START.match(line) and any(re.search(r"\bwrote:\s*$", l, re.I) for l in lines[i:i + 3]):
            cut = i
            break
    new = "\n".join(l.rstrip() for l in lines[:cut]).strip()
    new = re.sub(r"\n\s*\n+", "\n\n", new)
    quoted = "\n".join(lines[cut:])
    return new, quoted


def strip_footer(text, cuts):
    """Cut a fixed footer (Google Voice) at the first line holding one of the cut phrases."""
    low = text.lower()
    idx = [low.find(c.lower()) for c in cuts if c and low.find(c.lower()) >= 0]
    out = text[:min(idx)] if idx else text
    out = re.sub(r"^\s*<https://voice\.google\.com>\s*", "", out)
    return out.strip()


def split_signature(new):
    """(body, signature). The signature starts at a closing line, '--', 'Sent from my', or a paragraph after the
    first that looks like a name block. A legal notice is cut off first, so it never hides the name block."""
    lines = new.split("\n")
    legal_at = next((i for i, l in enumerate(lines) if i > 0 and _LEGAL.search(l)), None)
    head = lines[:legal_at] if legal_at is not None else lines
    tail = "\n".join(lines[legal_at:]).strip() if legal_at is not None else ""

    def join(sig):
        return "\n\n".join(x for x in (sig.strip(), tail) if x)

    for i, line in enumerate(head):
        st_ = line.strip()
        if i > 0 and (st_ in ("--", "-- ") or _SENT_FROM.match(st_) or _CLOSING.match(st_)):
            return "\n".join(head[:i]).strip(), join("\n".join(head[i:]))
    text = "\n".join(head)
    paras = re.split(r"\n\s*\n", text)
    for j in range(1, len(paras)):
        p = paras[j].strip("\n")
        plines = [l for l in p.split("\n") if l.strip()]
        if not plines:
            continue
        first = plines[0].strip()
        looks_name = bool(_NAME_LINE.match(first)) and first.split()[0].strip("*").lower() not in _NOT_NAMES
        short_block = all(len(l) < 70 for l in plines) and not any(l.rstrip().endswith("?") for l in plines)
        if (looks_name and short_block) or (_PHONE.search(p) and short_block and len(plines) <= 10
                                            and not re.search(r"[.!?]\s*$", plines[0])):
            return "\n\n".join(paras[:j]).strip(), join("\n\n".join(paras[j:]))
    return text.strip(), join("")


def quoted_signature(quoted):
    """A signature the sender put UNDER the quoted original (Gmail on phones does this): the block after '--'."""
    m = re.search(r"\n--\s*\n(.{0,600})", quoted or "", re.S)
    return m.group(1).strip() if m else ""


FREE_MAIL = ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com", "msn.com",
             "comcast.net", "att.net", "sbcglobal.net", "verizon.net", "me.com", "ymail.com", "protonmail.com",
             "bellsouth.net", "charter.net", "cox.net", "earthlink.net")


def domain_home_guess(addr):
    """'pat@maple-example-house.com' -> 'Maple Example House' (a guess; never for free mail)."""
    dom = (addr or "").split("@")[-1].lower()
    if not dom or dom in FREE_MAIL or "." not in dom:
        return None
    label = dom.split(".")[-2] if dom.count(".") >= 1 else dom
    if len(label) < 4:
        return None
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", label) if w)


def trim_legal(sig):
    """The signature without any legal notice (cut from the start of the line the notice is on)."""
    sig = sig or ""
    m = _LEGAL.search(sig)
    if not m:
        return sig.strip()
    return sig[:sig.rfind("\n", 0, m.start()) + 1].strip()


def shorten_links(text, limit=60):
    return _URL.sub(lambda m: m.group(0) if len(m.group(0)) <= limit else "[link]", text or "")


def is_opt_out(text):
    first = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    if _OPT_FIRST.match(first):
        rest = first[_OPT_FIRST.match(first).end():]
        joined = rest + " " + " ".join(l for l in (text or "").splitlines()[1:])
        if _ROOM_WORDS.search(joined) and not _OPT_PHRASES.search(text):
            return False  # "No, we don't have any rooms" answers the question; it is not "stop emailing"
        return True
    return bool(_OPT_PHRASES.search(text or ""))


_BUSINESS = re.compile(r"\b(llc|inc|corp|co|ltd|services|health|healthcare|living|care|center|centre|home|homes|house|"
                       r"village|senior|assisted|group|management|holdings|residence|residential|manor|gardens|"
                       r"terrace|lodge|place|estates|haven|community|enterprises|nursing|rehab)\b", re.I)


def _person(line):
    """The first name on a sign-off line like 'Pat Example, *Owner*' or '*Pat Example*', else None."""
    s = line.strip().strip("*").strip()
    cand = s.split(",")[0].strip().strip("*").strip()
    if not cand or _BUSINESS.search(cand) or _CLOSING.match(s) or _SENT_FROM.match(s):
        return None
    m = _NAME_LINE.match(cand)
    if not m or len(m.group(1).split()) > 3:
        return None
    tok = m.group(1).split()[0].strip("*.")
    return tok if tok.lower() not in _NOT_NAMES and len(tok) > 1 else None


def first_name_guess(body, sig, quoted_greeting=None, sender=""):
    """(name, source). From the sign-off block, else the greeting Joey used when the sender's address holds it."""
    for line in (sig or "").split("\n")[:5]:
        s = line.strip().strip("*").strip()
        if not s or _CLOSING.match(s) or _SENT_FROM.match(s) or s == "--":
            continue
        name = _person(s)
        if name:
            return name, "signature"
        break
    # a closing line inside the body: "Thanks,\nPat"
    lines = [l.strip() for l in (body or "").split("\n") if l.strip()]
    if len(lines) > 1 and len(lines[-1].split()) <= 3:
        name = _person(lines[-1])
        if name:
            return name, "sign-off"
    if quoted_greeting:
        local = (sender or "").split("@")[0].lower()
        if quoted_greeting.lower() in re.sub(r"[^a-z]", "", local):
            return quoted_greeting, "greeting"
    return None, None


def quoted_greeting(quoted):
    m = re.search(r"(?:^|\n)>?\s*\ufeff?(?:hi|hey|hello)\s+([A-Z][a-zA-Z'-]+)\s*,", quoted or "")
    return m.group(1) if m else None


def home_guess(quoted, sig, patterns):
    for p in patterns or []:
        m = re.search(p, re.sub(r"\n>\s*", " ", quoted or ""), re.I)
        if m:
            name = re.sub(r"\s+", " ", m.group("home")).strip(" ,.")
            name = re.sub(r",\s*the$", "", name, flags=re.I)  # "Maple House, The" (list order) -> "Maple House"
            if 1 < len(name) <= 80:
                return name, "campaign email"
    for line in (sig or "").split("\n")[:8]:
        s = line.strip().strip("*")
        if re.search(r"\b(assisted living|senior living|memory care|residential care|care center|care home|manor|"
                     r"village|gardens|residence|terrace|lodge|place|estates|haven|house|home)\b", s, re.I) \
                and len(s) < 70 and not _PHONE.search(s) and "@" not in s:
            return s, "signature"
    return None, None


def room_count(body):
    """The number of rooms/beds they named, if any (bare '2', '3 rooms', 'one room', 'a few')."""
    s = _PHONE.sub(" ", body or "")
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    first = next((l.strip() for l in s.splitlines() if l.strip()), "")
    m = re.fullmatch(r"(\d{1,3})(?:\s+(?:open\s+)?(?:rooms?|beds?|openings?|units?))?\s*[.!]?", first, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,3}|zero|none|one|two|three|four|five|six|seven|eight|nine|ten|a few|several)\s+"
                  r"(?:\w+\s+)?(?:rooms?|beds?|openings?|units?|vacanc\w*)\b", s, re.I)
    if m:
        v = m.group(1).lower()
        return int(v) if v.isdigit() else _WORD_NUM.get(v)
    return None
