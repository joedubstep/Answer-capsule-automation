"""Shared helpers for the lead list builder: paths, names, phones, time zones, home names.

Everything here is pure (no network, no files) so the tests can pin it down with synthetic rows.
"""
import os
import re
import sys

# Where the engine's state files live. On this cloud box the private state repo is cloned read-only here;
# on Joey's PC it is C:\\dev\\surven-outreach\\data\\carehome after `python tools/cloud_state.py pull`.
DEFAULT_DATA_DIRS = (
    os.environ.get("LEAD_LIST_DATA", ""),
    "/home/user/surven-carehome-state/data/carehome",
    "/home/user/aca-state/data/carehome",
)
DEFAULT_OUT = os.environ.get("LEAD_LIST_OUT", "/tmp/lead_list_out")
MIN_BEDS = 40  # Joey's rule since 10/23: 40+ beds only

# The engine (surven_outreach/carehome.py TITLE_NAMES) drops these from "Hi <name>,". We never set them at all.
TITLE_NAMES = {"lvn", "rn", "lpn", "cna", "bsn", "msn", "np", "md", "dr", "mr", "mrs", "ms", "owner", "admin",
               "administrator", "manager", "director", "miss", "sir", "madam", "rev", "pastor", "the", "staff",
               "vacant", "none", "na", "n/a", "tbd", "unknown", "interim", "acting", "executive"}
CREDENTIALS = {"rn", "lpn", "lvn", "cna", "bsn", "msn", "np", "md", "do", "phd", "mba", "mha", "lnha", "nha", "cdp",
               "cadc", "lcsw", "msw", "jr", "sr", "ii", "iii", "iv", "esq", "cpa", "ma", "ba", "bs", "rcal",
               "cal", "dr", "mr", "mrs", "ms", "miss", "rev"}

US_STATES = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix", "AR": "America/Chicago",
    "CA": "America/Los_Angeles", "CO": "America/Denver", "CT": "America/New_York", "DE": "America/New_York",
    "DC": "America/New_York", "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis", "IA": "America/Chicago",
    "KS": "America/Chicago", "KY": "America/New_York", "LA": "America/Chicago", "ME": "America/New_York",
    "MD": "America/New_York", "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver", "NE": "America/Chicago",
    "NV": "America/Los_Angeles", "NH": "America/New_York", "NJ": "America/New_York", "NM": "America/Denver",
    "NY": "America/New_York", "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York", "RI": "America/New_York",
    "SC": "America/New_York", "SD": "America/Chicago", "TN": "America/Chicago", "TX": "America/Chicago",
    "UT": "America/Denver", "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}
# Counties that sit in the other zone of a split state (send windows are the home's local 7-10 AM).
TZ_COUNTY_OVERRIDES = {
    # Florida panhandle west of the Apalachicola River is Central. Gulf County is split; see tz_for().
    "FL": ("America/Chicago", {"escambia", "santa rosa", "okaloosa", "walton", "holmes", "washington", "bay",
                               "jackson", "calhoun", "gulf"}),
    # Michigan's four Upper Peninsula counties on the Wisconsin line are Central.
    "MI": ("America/Chicago", {"gogebic", "iron", "dickinson", "menominee"}),
    # East Tennessee is Eastern; the rest of the state is Central (the default above).
    "TN": ("America/New_York", {"anderson", "blount", "bradley", "campbell", "carter", "claiborne", "cocke",
                                "grainger", "greene", "hamblen", "hamilton", "hancock", "hawkins", "jefferson",
                                "johnson", "knox", "loudon", "mcminn", "meigs", "monroe", "morgan", "polk", "rhea",
                                "roane", "scott", "sevier", "sullivan", "unicoi", "union", "washington"}),
}
EASTERN_GULF_CITIES = {"port st joe", "port st. joe", "port saint joe", "cape san blas", "indian pass"}


def safe_stdout():
    """On Joey's Windows PC a piped console is cp1252: an odd character in a state file's header must not crash a
    print. Unprintable characters become '?' instead."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def find_data_dir(explicit=""):
    for d in (explicit,) + DEFAULT_DATA_DIRS:
        if d and os.path.exists(os.path.join(d, "queue.json")):
            return d
    return explicit or ""


def tz_for(state, county="", city=""):
    st = (state or "").upper()
    base = US_STATES.get(st, "America/New_York")
    over = TZ_COUNTY_OVERRIDES.get(st)
    c = re.sub(r"\s+county$", "", (county or "").strip().lower())
    c = c.replace("st. ", "st ").replace("saint ", "st ")
    if over and c in over[1]:
        if st == "FL" and c == "gulf" and (city or "").strip().lower() in EASTERN_GULF_CITIES:
            return base
        return over[0]
    return base


def slug(s, limit=60):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] if "-" in s[:limit] else s[:limit]
    return s


def digits(s):
    return re.sub(r"\D", "", s or "")


def phone_e164(s):
    """'(555) 010-2233 ext 4' -> '+15550102233' (the lead_facts format). Anything else -> ''."""
    raw = (s or "").split("\n")[0]
    raw = re.split(r"(?i)\b(?:ext|x)\b\.?", raw)[0]
    d = digits(raw)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) != 10 or d[0] in "01":
        return ""
    return "+1" + d


SMALL = {"of", "at", "the", "and", "on", "by", "in", "for", "a", "an", "to", "dba"}
KEEP_UPPER_NAME = {"alf", "llc", "ii", "iii", "iv", "usa", "ltc", "ach", "ccrc", "ymca", "ywca"}


def _cap(word, first):
    lw = word.lower()
    if not first and lw in SMALL:
        return lw
    if lw in KEEP_UPPER_NAME:
        return lw.upper()
    out = "-".join(p[:1].upper() + p[1:] for p in lw.split("-"))
    out = re.sub(r"^Mc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
    out = re.sub(r"^O'([a-z])", lambda m: "O'" + m.group(1).upper(), out)
    out = re.sub(r"'S\b", "'s", out)
    return out


def nice_case(s):
    """Title-case a name that came in ALL CAPS (or all lower). Mixed case is the home's own spelling: kept."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    letters = [c for c in s if c.isalpha()]
    if not letters or (any(c.isupper() for c in letters) and any(c.islower() for c in letters)):
        return s
    words = s.split(" ")
    return " ".join(_cap(w, i == 0) for i, w in enumerate(words))


def clean_city(s):
    return nice_case((s or "").strip().strip(",")) if s else ""


def format_address(street, city, state, zip_code):
    """'205 GILES AVE', 'OMAHA', 'TX', '75571-1234' -> '205 Giles Ave, Omaha, TX 75571' (lead_facts style)."""
    street = nice_case(street or "")
    z = (zip_code or "").strip()
    z = z[:5] if re.match(r"^\d{5}", z) else z
    tail = " ".join(x for x in ((state or "").upper(), z) if x)
    return ", ".join(x for x in (street, clean_city(city), tail) if x)


# Words that mean the administrator cell holds a company, not a person ("ABC Senior Living LLC" must not become
# "Hi Abc,").
COMPANY_WORDS = {"llc", "inc", "corp", "corporation", "company", "co", "ltd", "lp", "llp", "pllc", "group", "holdings",
                 "management", "mgmt", "services", "partners", "enterprises", "associates", "trust", "senior", "seniors",
                 "living", "care", "health", "healthcare", "home", "homes", "center", "residence", "residences",
                 "assisted", "facility", "facilities", "village", "manor", "foundation", "ministries", "church",
                 "county", "properties", "operations", "operating", "ventures", "solutions", "network", "society"}
NAME_WORD = re.compile(r"[^\W\d_]+(?:['-][^\W\d_]+)*")


def _person_words(admin, order="first_last"):
    """Administrator cell -> the person's name words in first-to-last order, or [] when it is not one person.

    order is the state's habit when there is no comma: 'first_last' ('Pat A. Example') or 'last_first'
    ('EXAMPLE PAT A'). A comma always means 'Last, First' unless only credentials follow it ('Pat Example, RN')."""
    n = (admin or "").strip()
    if not n or "@" in n or any(ch.isdigit() for ch in n):
        return []
    n = re.sub(r"\(.*?\)", " ", n)
    n = n.split(";")[0].split("/")[0].split("&")[0].split(" and ")[0]
    if any(w.lower().strip(".,") in COMPANY_WORDS for w in n.split()):
        return []
    flip = order == "last_first"
    if "," in n:
        left, right = [x.strip() for x in n.split(",", 1)]
        right_words = [w for w in re.split(r"[\s.]+", right) if w]
        # 'Example, Pat' (last, first) vs 'Pat Example, RN' (credentials after the comma)
        if right_words and not all(w.lower().strip(".") in CREDENTIALS for w in right_words):
            n, flip = right + " " + left, False
        elif len(left.split()) > 1:
            n = left
        else:  # 'Example, RN': a last name and a credential, no first name
            return []
    words = [w.strip(".'\"") for w in re.split(r"\s+", n) if w.strip(".'\"")]
    words = [w for w in words if w.lower().strip(".") not in CREDENTIALS]
    if flip and len(words) > 1:
        words = words[1:] + words[:1]
    return words


def first_name(admin, order="first_last"):
    """Administrator field -> a first name for "Hi <first>," or '' when none is safe to use.

    Handles 'Example, Pat A.', 'Pat A. Example, RN', 'Dr. Pat Example', 'PAT EXAMPLE'. Titles, credentials,
    initials, company names and placeholder words never become a name (the engine had to strip "Hey Lvn," once,
    10/4)."""
    words = _person_words(admin, order)
    if not words:
        return ""
    w = words[0]
    if len(w) < 2 or not NAME_WORD.fullmatch(w) or w.lower() in TITLE_NAMES:
        return ""
    return _cap(w, True)


def last_name(admin, order="first_last"):
    words = _person_words(admin, order)
    if len(words) > 1 and NAME_WORD.fullmatch(words[-1]) and len(words[-1]) > 1:
        return _cap(words[-1], True)
    return ""


ABBREV_TOKENS = {"ctr", "vlg", "hm", "rcfe", "svc", "svcs", "fac", "assn", "mgmt", "corp", "li", "res", "inc",
                 "llc", "ltd", "dba", "alf", "ach", "snf", "lp", "llp", "pllc", "co", "hcr"}
STRIP_SUFFIX = re.compile(r"[\s,]+(?:l\.?l\.?c\.?|inc\.?|incorporated|corp\.?|corporation|ltd\.?|l\.?p\.?|pllc|co\.|"
                          r"a\.l\.f\.?|alf|ach)$", re.I)
DASHES = re.compile(r"\s+[-\u2013\u2014]\s+|[\u2013\u2014]")
YOUR_HOME = "your home"


def display_home(facility):
    """Official name -> (name used in the email copy, '' or why it fell back to "your home").

    Email 1 names the home ("how many rooms are open at <home> right now?"). A name that reads like a license
    record (abbreviations, codes, a stray letter, very long) would look machine-made, so the copy says
    "your home" instead, the same fallback the existing queue uses for 191 homes."""
    s = nice_case(facility or "")
    s = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^(.*?)[\s,]*\((?:the)\)$", s, re.I) or re.match(r"^(.*?),\s*the$", s, re.I)
    if m:
        s = "The " + m.group(1).strip()
    s = re.split(r"(?i)\s+d/?b/?a\s+", s)[-1]
    for _ in range(2):
        s = STRIP_SUFFIX.sub("", s).strip()
    parts = DASHES.split(s)
    if len(parts) > 1 and len(parts[0].strip()) >= 4:
        s = parts[0].strip()
    s = s.strip(" ,.-")
    words = s.split()
    low = [w.lower().strip(".,") for w in words]
    if not words or not any(c.isalpha() for c in s):
        return YOUR_HOME, "no usable name"
    if len(s) > 55:
        return YOUR_HOME, "name over 55 characters"
    if re.search(r"[#/\\@0-9]", s):
        return YOUR_HOME, "name has a number or symbol"
    if any(w in ABBREV_TOKENS for w in low):
        return YOUR_HOME, "name has an abbreviation"
    if len(words) > 1 and len(low[-1]) == 1:
        return YOUR_HOME, "name ends in a single letter"
    if len(s) < 4:
        return YOUR_HOME, "name too short"
    return s, ""


NAME_STOP = {"the", "llc", "inc", "co", "corp", "ltd", "dba", "alf", "al", "facility", "assisted", "living",
             "residence", "residences", "community", "communities", "care", "center", "centre", "ctr", "home",
             "homes", "senior", "seniors", "of", "at", "and", "for", "a", "an", "adult", "retirement", "memory",
             "llc.", "inc.", "rcfe", "village", "manor", "house", "place", "suites", "lodge"}


def norm_name(s):
    """Name key for dedupe: lower case, no punctuation, generic words dropped ('Sunny Oaks ALF, LLC' ->
    'sunny oaks'). If nothing distinctive is left, the full cleaned name is the key."""
    words = re.findall(r"[a-z0-9]+", (s or "").lower().replace("&", " and ").replace("'", ""))
    core = [w for w in words if w not in NAME_STOP]
    return " ".join(core or words)


def norm_city(s):
    c = re.sub(r"[^a-z ]+", " ", (s or "").lower())
    c = re.sub(r"\bsaint\b", "st", c)
    return re.sub(r"\s+", " ", c).strip()


def license_token(s):
    """The part of a license or file number that identifies the home: 'AL 12345' -> 'al12345'."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def id_license_token(pid):
    """Existing campaign ids end with the license or file number: 'fl-sunny-oaks-the-11900001' -> '11900001'.
    Returns '' when the tail is just a word of the name."""
    tail = (pid or "").rsplit("-", 1)[-1]
    return tail if sum(ch.isdigit() for ch in tail) >= 3 else ""
