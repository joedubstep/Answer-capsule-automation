"""Find an email address the home itself publishes. Never a guess.

Same approach as the engine's enrich_mail.site_emails (surven-carehome, 10/24): read the home's own site (home
page, contact, about, team, staff pages), take mailto links and plain-text addresses, drop junk. This version also
decodes Cloudflare-protected addresses and "[at]" spellings, and ranks what it finds:

  0 named   an address on the home's own domain with the administrator's first or last name in it
  1 list    the address on the state license list (when the state publishes one)
  2 role    admissions@, director@, administrator@, marketing@... on the home's own domain
  3 front   info@, contact@, office@... on the home's own domain
  4 staff   any other address on the home's own domain
  5 free    a gmail/yahoo/... address printed on the home's own site

Addresses at any other business domain (the web designer, a vendor, a directory) are never used. The engine's
nightly verify_mail run still asks each mail server before the first email goes out.
"""
import re
import urllib.parse
from html import unescape

from .web import Blocked
from .website import base_domain

PAGES = ["", "contact", "contact-us", "contactus", "about", "about-us", "our-team", "team", "staff", "leadership",
         "our-staff", "meet-our-team", "careers"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ROLE = re.compile(r"^(admissions?|director|executivedirector|ed|administrator|admin|marketing|sales|tours?|"
                  r"move-?in|community|leasing|inquiries|enquiries|welcome|residentservices|careteam)", re.I)
GENERIC = re.compile(r"^(info|contact|hello|office|mail|frontdesk|reception|main|general)", re.I)
JUNK = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js)$|example\.|sentry|wixpress|godaddy|squarespace|@2x|noreply|"
                  r"no-reply|donotreply|privacy|abuse|webmaster|hr@|jobs@|careers@|billing|accounts?@|payroll|"
                  r"domain|support@wix|user@|name@|email@|yourname|youremail|test@|@sentry", re.I)
FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "msn.com", "live.com",
            "comcast.net", "att.net", "sbcglobal.net", "bellsouth.net", "verizon.net", "me.com", "ymail.com",
            "earthlink.net", "charter.net", "cox.net", "frontier.com", "windstream.net", "embarqmail.com"}
LABEL = {0: "the home's own website (named person)", 1: "state facility list",
         2: "the home's own website (role inbox)", 3: "the home's own website (front-desk inbox)",
         4: "the home's own website (staff address)", 5: "the home's own website (free-mail address printed there)"}


def cf_decode(hexstr):
    """Cloudflare email protection: first byte is the XOR key."""
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""


def extract(html):
    """Every address in a page, in the order found (mailto links first)."""
    h = unescape(html or "")
    found = []
    for m in re.finditer(r'data-cfemail="([0-9a-fA-F]+)"', h):
        found.append(cf_decode(m.group(1)))
    for m in re.finditer(r"/cdn-cgi/l/email-protection#([0-9a-fA-F]+)", h):
        found.append(cf_decode(m.group(1)))
    for m in re.finditer(r"""(?i)mailto:([^"'?>\s]+)""", h):
        found.append(urllib.parse.unquote(m.group(1)))
    h2 = re.sub(r"\s*[\[(]\s*at\s*[\])]\s*", "@", h, flags=re.I)
    h2 = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", h2, flags=re.I)
    found += EMAIL.findall(h2)
    out = []
    for e in found:
        e = e.strip().strip(".,;:").lower()
        if EMAIL.fullmatch(e) and not JUNK.search(e) and e not in out:
            out.append(e)
    return out


def classify(addr, site_dom, first="", last=""):
    """-> rank (0-5) or None when the address must not be used for this home."""
    user, _, dom = addr.partition("@")
    bd = base_domain(dom)
    own = bool(site_dom) and bd == base_domain(site_dom)
    if dom in FREEMAIL:
        return 5
    if not own:
        return None
    f, l = (first or "").lower(), (last or "").lower()
    if (len(f) > 2 and f in user) or (len(l) > 2 and l in user):
        return 0
    if ROLE.match(user):
        return 2
    if GENERIC.match(user):
        return 3
    return 4


def site_emails(site, fetch_fn, first_html=None, stop_rank=2, first="", last=""):
    """-> [(address, page url)] from the home's own pages. Stops early once a named or role address is found."""
    found, seen = [], set()
    base = site if site.startswith("http") else "https://" + site
    pu = urllib.parse.urlparse(base)
    path = pu.path.rsplit("/", 1)[0] if "." in pu.path.rsplit("/", 1)[-1] else pu.path
    root = f"{pu.scheme}://{pu.netloc}{path.rstrip('/')}/"  # relative to the home's page (chain sites)
    site_dom = pu.netloc
    for i, page in enumerate(PAGES):
        url = base if page == "" else urllib.parse.urljoin(root, page)
        html = None
        if page == "" and first_html is not None:
            html = first_html
        else:
            try:
                p = fetch_fn(url)
            except Blocked:
                raise
            except OSError:
                if page == "":
                    return found  # the site itself does not load
                p = None
            if p is not None and p.status < 400:
                html = p.text
        for e in extract(html or ""):
            if e not in seen:
                seen.add(e)
                found.append((e, url))
        ranks = [r for r in (classify(e, site_dom, first, last) for e, _ in found) if r is not None]
        best = min(ranks) if ranks else None
        # a named address ends the search; a role or front-desk one does once contact and about were read
        if best == 0 or (best is not None and best <= stop_rank + 1 and i >= PAGES.index("about-us")):
            break
    return found


def choose(found, site, list_email="", first="", last="", state=""):
    """-> {"email", "email_source", "email_page", "emails_found"} with the best usable address, or no email."""
    site_dom = urllib.parse.urlparse(site if "://" in site else "https://" + site).netloc if site else ""
    cands = []
    for e, page in found:
        r = classify(e, site_dom, first, last)
        if r is not None:
            cands.append((r, e, page))
    if list_email and EMAIL.fullmatch(list_email) and not JUNK.search(list_email):
        r = classify(list_email, site_dom, first, last)
        cands.append((0 if r == 0 else 1, list_email, "state license list"))
    cands.sort(key=lambda x: x[0])
    out = {"email": "", "email_source": "", "email_page": "", "emails_found": [e for e, _ in found]}
    if cands:
        r, e, page = cands[0]
        src = LABEL[r] if page != "state license list" else f"{state} state facility list".strip()
        if page == "state license list" and r == 0:
            src = f"{state} state facility list (named person)".strip()
        out.update({"email": e, "email_source": src, "email_page": page})
    return out
