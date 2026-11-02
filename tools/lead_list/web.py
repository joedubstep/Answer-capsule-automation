"""Small stdlib web client for the website and email steps, with a clear "blocked" signal.

A cloud session whose network policy denies a host gets a proxy 403 on CONNECT (or a DNS failure for every
host). That is not the home's fault, so it raises Blocked and the pipeline stops the web step instead of
marking 1,000 homes "no website". Tests pass their own fetch function, so nothing here runs offline.
"""
import http.client
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0.0.0 Safari/537.36")


class Blocked(Exception):
    """The network itself refused (proxy policy), so no answer about this host means anything."""


class Page:
    def __init__(self, status, url, text):
        self.status, self.url, self.text = status, url, text

    def __repr__(self):
        return f"Page({self.status}, {self.url!r}, {len(self.text)} chars)"


def _is_block(err):
    s = str(getattr(err, "reason", err))
    return bool(re.search(r"Tunnel connection failed: 40[37]|CONNECT tunnel failed|403 Forbidden.*tunnel", s, re.I))


def fetch(url, timeout=15, max_bytes=2_000_000, data=None, headers=None):
    """GET (or POST with data) -> Page. Raises Blocked on a proxy policy denial, OSError on other failures."""
    h = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en-US"}
    h.update(headers or {})
    try:
        req = urllib.request.Request(url, data=data, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes)
            return Page(r.status, r.geturl(), _text(raw, r.headers.get_content_charset()))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(200_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return Page(e.code, url, body)
    except urllib.error.URLError as e:
        if _is_block(e):
            raise Blocked(f"{urllib.parse.urlparse(url).netloc}: {e.reason}") from e
        raise OSError(str(e.reason)) from e
    except (socket.timeout, TimeoutError, ssl.SSLError, ConnectionError) as e:
        raise OSError(str(e)) from e
    except (http.client.HTTPException, ValueError) as e:  # a broken server or a malformed link is a dead site
        raise OSError(f"{type(e).__name__}: {e}") from e


def _text(raw, charset):
    try:
        return raw.decode(charset or "utf-8", "replace")
    except LookupError:  # a charset name Python does not know ("utf8mb4", "none"...)
        return raw.decode("utf-8", "replace")


def fetch_bytes(url, timeout=60, max_bytes=60_000_000):
    """Download a data file -> bytes. Raises Blocked or OSError."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(max_bytes)
    except urllib.error.HTTPError as e:
        raise OSError(f"HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        if _is_block(e):
            raise Blocked(f"{urllib.parse.urlparse(url).netloc}: {e.reason}") from e
        raise OSError(str(e.reason)) from e
    except (http.client.HTTPException, ValueError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise OSError(f"{type(e).__name__}: {e}") from e


def egress(url, fetch_fn=fetch):
    """'open' when the network lets this session reach url's host, 'blocked' when policy denies it, else 'down'."""
    try:
        fetch_fn(url, timeout=12)
        return "open"
    except Blocked:
        return "blocked"
    except OSError as e:
        return "blocked" if re.search(r"Name or service not known|getaddrinfo|nodename", str(e)) else "down"


def visible_text(html):
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t))


def links(html, base, with_text=False):
    """Absolute link targets in a page; with_text=True gives (url, the link's visible words) pairs."""
    out, html = [], html or ""
    for m in re.finditer(r"""(?i)<a\s[^>]*href\s*=\s*["']([^"'#]+)["'][^>]*>""", html):
        url = urllib.parse.urljoin(base, unescape(m.group(1)).strip())
        if not with_text:
            out.append(url)
            continue
        rest = html[m.end():m.end() + 600]
        cut = re.search(r"(?i)</a\s*>|<a\s", rest)
        out.append((url, visible_text(rest[:cut.start()] if cut else rest[:200]).strip()))
    return out


class Polite:
    """Wraps a fetch function: at most one request per host every `gap` seconds (threads share it)."""

    SLOW = {"html.duckduckgo.com": 3.0}  # a search engine throttles fast callers; one query every 3 seconds

    def __init__(self, fetch_fn=fetch, gap=0.4):
        import threading
        self.fetch_fn, self.gap, self.last, self.lock = fetch_fn, gap, {}, threading.Lock()

    def __call__(self, url, **kw):
        host = urllib.parse.urlparse(url).netloc
        gap = self.SLOW.get(host, self.gap)
        with self.lock:
            wait = self.last.get(host, 0) + gap - time.time()
            self.last[host] = max(time.time(), self.last.get(host, 0) + gap)
        if wait > 0:
            time.sleep(wait)
        return self.fetch_fn(url, **kw)
