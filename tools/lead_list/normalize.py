"""Raw license row -> one normalized home record (the fields lead_facts.json and queue.json need, plus sources).

The record keeps where each fact came from: the phone's column, the first name's column, the website's origin,
so review.csv can show Joey and the loader exactly what is primary data and what was found later.
"""
import re

from . import common


def _int(v):
    m = re.search(r"\d[\d,]*", str(v or ""))
    return int(m.group(0).replace(",", "")) if m else None


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def first_email(v):
    """A state list's email cell can hold two addresses ('a@x.test; b@x.test') or 'mailto:'. -> the first one."""
    m = EMAIL.search(v or "")
    return m.group(0).lower() if m else ""


def make_id(state, facility, license_no, city=""):
    """Same shape as the existing ids ('fl-sunny-oaks-the-11900001'): state, name slug, license token.
    With no license number it ends with the city instead (the MA precedent: 'rebuilt from name + city')."""
    tail = common.license_token(license_no) or common.slug(city) or "nolicense"
    base = f"{state.lower()}-{common.slug(facility, 55)}"
    return f"{base}-{tail}"


def normalize(source, row, mapping):
    """source: a sources.base.Source; row: dict keyed by original headers; mapping: {field: header}."""
    def get(field):
        h = mapping.get(field)
        return (row.get(h) or "").strip() if h else ""

    official = re.sub(r"\s+", " ", get("name"))
    facility = common.nice_case(official)
    city = common.clean_city(get("city"))
    county = common.nice_case(get("county"))
    license_no = source.license_of(get)
    admin_header = "administrator" if get("administrator") else ("ceo" if get("ceo") else "")
    admin = get(admin_header) if admin_header else ""
    order = getattr(source, "admin_order", "first_last")
    first = common.first_name(admin, order)
    home, home_flag = common.display_home(official)
    phone = common.phone_e164(get("phone"))
    rec = {
        "state": source.state,
        "source": source.code,
        "license": license_no,
        "license_no": get("license_no"),
        "official_name": official,
        "facility": facility,
        "home": home,
        "home_check": home_flag,
        "street": get("address"),
        "city": city,
        "zip": get("zip"),
        "county": county,
        "phone": phone,
        "phone_source": source.phone_source(mapping.get("phone", "")) if phone else "",
        "beds": _int(get("beds")),
        "beds_word": source.beds_word,
        "type": get("type"),
        "status": get("status"),
        "memory": get("memory"),
        "admin_raw": admin,
        "first_name": first,
        "last_name": common.last_name(admin, order) if admin else "",
        "first_name_source": (f"{source.agency}, column '{mapping.get(admin_header)}'" if first else
                              ("administrator field not usable as a first name" if admin else
                               "no administrator on the state list")),
        "list_email": first_email(get("email")),
        "list_website": get("website"),
        "licensee": common.nice_case(get("licensee")),
        "profile_id": get("profile_id"),
    }
    rec["address"] = common.format_address(rec["street"], city, source.state, rec["zip"])
    rec["care"] = source.care_label(rec)
    rec["tz"] = source.tz(rec)
    rec["id"] = make_id(source.state, official or facility, license_no, city)
    return rec


def normalize_all(source, rows, mapping):
    return [normalize(source, r, mapping) for r in rows if any((v or "").strip() for v in r.values())]
