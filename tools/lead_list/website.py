"""Find a home's own website, and only keep it when the page proves it is that home.

Order: the website on the state license list; then a site Claude found with WebSearch (passed in --sites);
then a DuckDuckGo HTML search (a plain GET, works from a PC or any open network). A searched site counts only
when the page shows the home's phone number or its street address; a list website counts when it loads.
Directory and listing sites (A Place for Mom, Caring.com, Yelp, Facebook...) never count as the home's site.
"""
import re
import urllib.parse

from . import common
from .web import Blocked, visible_text

DIRECTORIES = {
    "aplaceformom.com", "caring.com", "seniorly.com", "senioradvisor.com", "seniorhousingnet.com", "yelp.com",
    "facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "healthgrades.com",
    "assisted-living-directory.com", "assistedlivingfacilities.org", "seniorliving.org", "senioradvice.com",
    "mapquest.com", "yellowpages.com", "bbb.org", "medicare.gov", "google.com", "bing.com", "duckduckgo.com",
    "wikipedia.org", "indeed.com", "glassdoor.com", "zillow.com", "agingcare.com", "payingforseniorcare.com",
    "seniorcare.com", "careforth.com", "carelistings.com", "assistedliving.com", "assistedlivingcenter.com",
    "mylife.com", "manta.com", "dnb.com", "opencorporates.com", "bizapedia.com", "seniorguidance.org",
    "argentum.org", "usnews.com", "newsbreak.com", "chamberofcommerce.com", "nextdoor.com", "angi.com",
    "everyplace.care", "silvertechdirectory.com", "bytescraper.com", "provider-profile.com", "npino.com",
    "npiprofile.com", "caredash.com", "seniorhomes.com", "senior-living.com", "seniorlivingnearme.com",
    "theseniorlist.com", "care.com", "familyassets.com", "eldercarelink.com", "healthfinder.fl.gov",
    "floridahealthfinder.gov", "ncdhhs.gov", "apps.lara.state.mi.us", "governmentjobs.com", "ziprecruiter.com",
}


def domain(url):
    host = urllib.parse.urlparse(url if "://" in url else "https://" + url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def base_domain(host_or_url):
    h = domain(host_or_url) if ("/" in host_or_url or ":" in host_or_url) else host_or_url.lower()
    h = h[4:] if h.startswith("www.") else h
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def is_directory(url):
    d = domain(url)
    return any(d == x or d.endswith("." + x) for x in DIRECTORIES) or d.endswith(".gov")


def normalize_url(u):
    u = (u or "").strip().strip(",;")
    if not u or " " in u or "." not in u:
        return ""
    return u if u.lower().startswith(("http://", "https://")) else "https://" + u.lstrip("/")


def confirm(html, rec):
    """Does this page belong to the home? -> 'phone on page', 'address on page' or ''."""
    text = visible_text(html)
    ph = common.digits(rec.get("phone", ""))[-10:]
    if len(ph) == 10:
        pat = rf"\(?{ph[:3]}\)?[\s.\-\u2013]*{ph[3:6]}[\s.\-\u2013]*{ph[6:]}"
        if re.search(pat, text) or ph in common.digits(text):
            return "phone on page"
    street = (rec.get("street") or "").strip()
    m = re.match(r"^(\d+)\s+(?:[NSEW]\.?\s+)?([A-Za-z][A-Za-z']+)", street)
    if m:
        num, word = m.group(1), m.group(2)
        if re.search(rf"\b{num}\b[^<]{{0,25}}\b{re.escape(word)}", text, re.I):
            return "address on page"
    return ""


def ddg_results(html):
    """Result links from a DuckDuckGo HTML search page (the real target sits in the uddg= parameter)."""
    out = []
    for m in re.finditer(r'''(?i)<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"''', html or ""):
        href = m.group(1).replace("&amp;", "&")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        url = q.get("uddg", [href])[0]
        if url.startswith("http") and url not in out:
            out.append(url)
    return out


SEARCH = {"off": False, "why": "", "fails": 0}  # shared by the run's threads


class SearchRefused(Exception):
    """The search engine pushed back, so this home was not really searched. The run leaves it uncached."""


def search(rec, fetch_fn, n=4):
    """Top non-directory results for '"<name>" <city> <state>'. When the search engine pushes back (rate limit,
    "anomaly" check) it raises SearchRefused, so that home is retried next run; after three refusals search
    switches off for the rest of the run instead of burning the time budget. List websites and --sites still work."""
    if SEARCH["off"]:
        raise SearchRefused(SEARCH["why"])
    q = f'"{rec.get("official_name") or rec.get("facility")}" {rec.get("city", "")} {rec.get("state", "")}'
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q)
    try:
        page = fetch_fn(url)
    except Blocked:
        raise
    except OSError as e:  # a timeout is not an answer: retry this home next run
        raise SearchRefused(f"search failed: {e}") from e
    if page.status in (202, 403, 429) or "anomaly" in (page.text or "")[:20000].lower():
        SEARCH["fails"] += 1
        if SEARCH["fails"] >= 3:
            SEARCH.update(off=True, why=f"search engine refused (HTTP {page.status})")
        raise SearchRefused(f"HTTP {page.status}")
    return [u for u in ddg_results(page.text) if not is_directory(u)][:n]


def with_www(url):
    """'https://sunny.test/x' -> 'https://www.sunny.test/x' ('' when the host already has www. or is an IP)."""
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower()
    if not host or host.startswith("www.") or re.match(r"^[\d.:]+$", host):
        return ""
    return urllib.parse.urlunparse(p._replace(netloc="www." + p.netloc))


def _load(url, fetch_fn, www_retry=True):
    """Fetch a candidate site. A list website often leaves out "www." and some homes' sites answer only with it
    (the engine's enrich_mail.site_emails retries the same way). -> Page with a usable body, or None."""
    for u in (url, with_www(url) if www_retry else ""):
        if not u:
            continue
        try:
            page = fetch_fn(u)
        except Blocked:
            raise
        except OSError:
            continue
        if page.status < 400 and page.text:
            return page
    return None


def find(rec, fetch_fn, extra_site="", use_search=True):
    """-> {"website", "website_source", "html"} or {} when no site proves to be the home's."""
    tried = set()
    cands = []
    lw = normalize_url(rec.get("list_website"))
    if lw and not is_directory(lw):
        cands.append((lw, "list"))
    es = normalize_url(extra_site)
    if es:
        cands.append((es, "claude"))
    for kind in ("list", "claude", "search"):
        if kind == "search":
            if not use_search:
                break
            cands = [(u, "search") for u in search(rec, fetch_fn)]
        for url, k in [c for c in cands if c[1] == kind]:
            if base_domain(url) in tried:
                continue
            tried.add(base_domain(url))
            page = _load(url, fetch_fn, www_retry=k != "search")
            if page is None:
                continue
            if page.status >= 400 or not page.text:
                continue
            how = confirm(page.text, rec)
            if k == "list":
                src = "state license list" + (f", confirmed by {how}" if how else "")
            elif how:
                src = ("web search by Claude" if k == "claude" else "DuckDuckGo search result") + \
                      f", confirmed by {how}"
            else:
                continue
            final = page.url or url
            return {"website": final, "website_source": src, "html": page.text}
    return {}
