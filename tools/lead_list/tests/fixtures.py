"""Synthetic test data only (the repo is public). Names like "Pat Example", 555 phone numbers, .test domains.

make_engine_dir() builds a fake engine data/carehome folder with the REAL schemas: carehome.db tables copied from
surven_outreach/carehome.py, queue.json v3 entries, lead_facts.json, build/prospects.json and email_verify.json,
written the way the PC writes them (CRLF, no final newline, indent 1 / 0) so merge tests can prove layout is kept.
"""
import io
import json
import os
import sqlite3
import zipfile

from tools.lead_list.web import Blocked, Page

SCHEMA = """
CREATE TABLE prospects (
  id TEXT PRIMARY KEY, email TEXT NOT NULL, facility TEXT, first_name TEXT, tz TEXT,
  rank INTEGER DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
  current_step INTEGER NOT NULL DEFAULT 0, thread_message_id TEXT, thread_subject TEXT,
  first_sent_on TEXT, last_sent_on TEXT, stopped_reason TEXT, stopped_on TEXT
, sender TEXT);
CREATE TABLE sends (
  id INTEGER PRIMARY KEY AUTOINCREMENT, prospect_id TEXT NOT NULL, step INTEGER NOT NULL,
  email TEXT, subject TEXT, body TEXT, message_id TEXT, sent_at TEXT NOT NULL, sender TEXT,
  UNIQUE(prospect_id, step)
);
"""


def v3_entry(pid, email, facility, first, tz, rank, variant="A"):
    hi = f"Hi {first}, " if first else "Hi, "
    return {"id": pid, "email": email, "facility": facility, "first_name": first, "tz": tz, "rank": rank,
            "variant": variant, "seq": "v3", "home": facility,
            "emails": {"1": {"subject": "Do you have an open room?",
                             "body": hi + f"how many rooms are open at {facility} right now?\n\nJoey"},
                       "2": {"body": "Hey, I just emailed you.\n\nJoey"}, "3": {"pending": True},
                       "4": {"body": "I'm closing this out and will stop emailing.\n\nJoey"}}}


def fact(facility, city, state, phone, beds=60, tz="America/New_York"):
    return {"facility": facility, "city": city, "state": state, "website": "", "website_source": "",
            "address": f"1 Main St, {city}, {state} 00000", "beds": beds, "beds_word": "beds",
            "care": "assisted living facility", "tz": tz, "census": None, "open_beds": None, "census_date": "",
            "phone": phone, "phone_source": "synthetic"}


def _dump_pc(path, obj, indent, ensure_ascii):
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=ensure_ascii)


def make_engine_dir(root, today="2026-11-02"):
    d = os.path.join(root, "data", "carehome")
    os.makedirs(os.path.join(d, "build"), exist_ok=True)
    queue = [
        v3_entry("fl-sunny-oaks-example-11900001", "pat@sunnyoaks.test", "Sunny Oaks Example", "Pat",
                 "America/New_York", -100),
        v3_entry("fl-harbor-view-example-11900002", "info@harborview.test", "Harbor View Example", "",
                 "America/New_York", -101, "B"),
        v3_entry("nc-pine-ridge-example-ach0001", "office@pineridge.test", "Pine Ridge Example", "Lee",
                 "America/New_York", -102),
        v3_entry("ga-café-example-123", "x@cafe.test", "Café Example", "", "America/New_York", -50),
    ]
    facts = {
        "fl-sunny-oaks-example-11900001": fact("Sunny Oaks Example", "Exampleton", "FL", "+19045550101"),
        "fl-harbor-view-example-11900002": fact("Harbor View Example", "Bayville", "FL", "+19045550102"),
        "nc-pine-ridge-example-ach0001": fact("Pine Ridge Example", "Raleigh", "NC", "+19195550103"),
        "fl-old-mill-example-11900009": fact("Old Mill Example", "Millburg", "FL", "+19045550109", beds=20),
    }
    people = [{"id": "fl-sunny-oaks-example-11900001", "facility": "Sunny Oaks Example", "state": "FL",
               "address": "1 Main St, Exampleton, FL 00000", "email": "pat@sunnyoaks.test",
               "email_source": "the home's own website (named person)", "contact_name": "Pat Example"},
              {"id": "nc-pine-ridge-example-ach0001", "facility": "Pine Ridge Example", "state": "NC",
               "address": "2 Main St, Raleigh, NC 00000", "email": "office@pineridge.test",
               "email_source": "NC state facility list", "contact_name": ""}]
    verdicts = {"pat@sunnyoaks.test": {"status": "valid", "checked": today},
                "info@harborview.test": {"status": "catch_all", "checked": today},
                "office@pineridge.test": {"status": "valid", "checked": today},
                "x@cafe.test": {"status": "invalid", "checked": today}}
    _dump_pc(os.path.join(d, "queue.json"), queue, 1, False)
    _dump_pc(os.path.join(d, "lead_facts.json"), facts, 0, True)
    _dump_pc(os.path.join(d, "build", "prospects.json"), people, 1, True)
    with open(os.path.join(d, "email_verify.json"), "w", encoding="utf-8") as f:
        json.dump(verdicts, f)
    con = sqlite3.connect(os.path.join(d, "carehome.db"))
    con.executescript(SCHEMA)
    rows = [("fl-sunny-oaks-example-11900001", "pat@sunnyoaks.test", "Sunny Oaks Example", "queued"),
            ("fl-harbor-view-example-11900002", "info@harborview.test", "Harbor View Example", "queued"),
            ("nc-pine-ridge-example-ach0001", "office@pineridge.test", "Pine Ridge Example", "active"),
            ("ga-café-example-123", "x@cafe.test", "Café Example", "queued"),
            ("tx-gone-example-5551", "owner@gone.test", "Gone Example", "skipped")]
    for pid, e, fac, st in rows:
        con.execute("INSERT INTO prospects (id,email,facility,first_name,tz,status) VALUES (?,?,?,?,?,?)",
                    (pid, e, fac, "", "America/New_York", st))
    for i, day in enumerate(["2026-10-27", "2026-10-29", "2026-10-30", "2026-11-01"]):
        con.execute("INSERT INTO sends (prospect_id,step,email,sent_at) VALUES (?,?,?,?)",
                    (f"sent-{i}", 1, f"s{i}@x.test", day + "T09:00:00-04:00"))
    con.commit()
    con.close()
    return d


FL_HEADERS = ["Name", "Street Address", "Street City", "Street State", "Street Zip", "Street County", "Phone Number",
              "File Number", "License Number", "Licensed Beds", "Administrator", "Provider Type", "License Status",
              "Website", "Owner", "Specialty Licenses"]
FL_ROWS = [
    # new, 80 beds, website with a named email
    ["MAPLE GROVE EXAMPLE", "100 OAK ST", "EXAMPLE CITY", "FL", "32000", "DUVAL", "(904) 555-0201", "11900101",
     "AL1001", "80", "EXAMPLE, PAT", "Assisted Living Facility", "Licensed", "www.maplegrove.test", "MG LLC",
     "LNS, ECC"],
    # new, 45 beds, panhandle (Central), role email on site
    ["BAYSIDE EXAMPLE (THE)", "200 BAY RD", "PENSACOLA", "FL", "32500", "ESCAMBIA", "850-555-0202", "11900102",
     "AL1002", "45", "Lee Example, RN", "Assisted Living Facility", "Licensed", "https://bayside.test", "", ""],
    # under 40 beds
    ["TINY EXAMPLE HOME", "300 ELM ST", "EXAMPLE CITY", "FL", "32000", "DUVAL", "904-555-0203", "11900103", "AL1003",
     "12", "SAM EXAMPLE", "Assisted Living Facility", "Licensed", "", "", ""],
    # already in the campaign by file number (11900001)
    ["SUNNY OAKS EXAMPLE", "1 MAIN ST", "EXAMPLETON", "FL", "32001", "CLAY", "904-555-0101", "11900001", "AL1004",
     "60", "PAT EXAMPLE", "Assisted Living Facility", "Licensed", "", "", ""],
    # already in the campaign by phone only
    ["HARBOR VIEW EXAMPLE II", "9 DOCK ST", "BAYVILLE", "FL", "32002", "CLAY", "904-555-0102", "11900199", "AL1005",
     "90", "", "Assisted Living Facility", "Licensed", "", "", ""],
    # closed license
    ["CLOSED EXAMPLE", "400 PINE ST", "EXAMPLE CITY", "FL", "32000", "DUVAL", "904-555-0204", "11900104", "AL1006",
     "120", "ALEX EXAMPLE", "Assisted Living Facility", "Closed", "", "", ""],
    # not assisted living
    ["NURSING EXAMPLE", "500 CEDAR ST", "EXAMPLE CITY", "FL", "32000", "DUVAL", "904-555-0205", "11900105",
     "SNF1007", "150", "JO EXAMPLE", "Nursing Home", "Licensed", "", "", ""],
    # new, no website anywhere -> searched; page confirms by phone; front-desk email
    ["RIVER BEND EXAMPLE", "600 RIVER RD", "EXAMPLE CITY", "FL", "32000", "DUVAL", "904-555-0206", "11900106",
     "AL1008", "55", "ADMINISTRATOR", "Assisted Living Facility", "Licensed", "", "", ""],
    # new, website shows no email -> excluded "no published email found"
    ["QUIET PINES EXAMPLE", "700 QUIET LN", "EXAMPLE CITY", "FL", "32000", "DUVAL", "904-555-0207", "11900107",
     "AL1009", "70", "CHRIS EXAMPLE", "Assisted Living Facility", "Licensed", "quietpines.test", "", ""],
    # new, same email as Maple Grove (a chain inbox) -> the smaller one is dropped
    ["MAPLE GROVE EXAMPLE NORTH", "800 OAK ST", "EXAMPLE CITY", "FL", "32000", "DUVAL", "904-555-0208", "11900108",
     "AL1010", "50", "EXAMPLE, PAT", "Assisted Living Facility", "Licensed", "maplegrove.test", "", ""],
]


def write_fl_csv(path):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FL_HEADERS)
        w.writerows(FL_ROWS)
    return path


def xlsx_bytes(rows):
    """A minimal real .xlsx (inline strings) built with zipfile."""
    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    sheet_rows = []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{col(ci)}{ri}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                v = str(v).replace("&", "&amp;").replace("<", "&lt;")
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>')
        sheet_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook {ns} {rns}><sheets>'
                   '<sheet name="Listing" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" '
                   'Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<?xml version="1.0"?><worksheet {ns}><sheetData>'
                   f'{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


NC_ROWS = [
    ["Adult Care Home Listing (synthetic)"],
    [],
    ["Facility Name", "License Number", "County", "Facility Address", "Facility City", "Facility Zip",
     "Facility Phone", "Administrator", "Licensed Beds", "Special Care Unit Beds", "Facility Type"],
    ["OAKWOOD EXAMPLE", "HAL-001-001", "WAKE", "10 FIRST ST", "RALEIGH", "27600", "919-555-0301",
     "Robin Example", 96, 24, "Adult Care Home"],
    ["PINE RIDGE EXAMPLE", "ACH0001", "WAKE", "2 MAIN ST", "RALEIGH", "27600", "919-555-0103", "Lee Example", 60, 0,
     "Adult Care Home"],
    ["SMALL FAMILY EXAMPLE", "FCL-001-002", "WAKE", "11 SECOND ST", "RALEIGH", "27600", "919-555-0302",
     "Dana Example", 6, 0, "Family Care Home"],
    ["MIDSIZE EXAMPLE", "HAL-001-003", "DURHAM", "12 THIRD ST", "DURHAM", "27700", "919-555-0303", "", 39, 0,
     "Adult Care Home"],
]


def write_nc_xlsx(path):
    with open(path, "wb") as f:
        f.write(xlsx_bytes(NC_ROWS))
    return path


SITES = {
    "https://www.maplegrove.test": '<html><body>Maple Grove Example. Call (904) 555-0201. '
                                   '<a href="mailto:pat.example@maplegrove.test">Email Pat</a> '
                                   '<a href="mailto:info@maplegrove.test">info</a></body></html>',
    "https://bayside.test": '<html><body>Bayside. 200 Bay Rd, Pensacola. <a href="/contact">Contact</a></body></html>',
    "https://bayside.test/contact": '<p>Tours: admissions [at] bayside.test or our designer web@designer.test</p>',
    "https://quietpines.test": "<html><body>Quiet Pines Example. 700 Quiet Ln.</body></html>",
    "https://maplegrove.test": '<html>Maple Grove North <a href="mailto:info@maplegrove.test">x</a> '
                               '<a href="mailto:pat.example@maplegrove.test">p</a> 904-555-0208</html>',
    "https://riverbend.test/": "<html>River Bend Example, 600 River Rd. Phone 904.555.0206. "
                               '<span class="__cf_email__" data-cfemail="CFEMAIL"></span></html>',
}


def cf_encode(addr, key=0x42):
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in addr)


SITES["https://riverbend.test/"] = SITES["https://riverbend.test/"].replace("CFEMAIL",
                                                                           cf_encode("frontdesk@riverbend.test"))
DDG = ('<div><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.caring.com%2Fx&rut=1">dir</a>'
       '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Friverbend.test%2F&rut=2">River Bend</a>'
       '</div>')


class FakeWeb:
    """fetch(url) from a dict. Unknown URLs fail like a dead site. blocked=True acts like a proxy denial."""

    def __init__(self, pages=None, blocked=False):
        self.pages = dict(SITES if pages is None else pages)
        self.blocked = blocked
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append(url)
        if self.blocked:
            raise Blocked("example.test: Tunnel connection failed: 403 Forbidden")
        if "duckduckgo.com/html" in url:
            return Page(200, url, DDG if "River+Bend" in url or "RIVER+BEND" in url else "<div></div>")
        for k in (url, url.rstrip("/"), url.rstrip("/") + "/"):
            if k in self.pages:
                return Page(200, k, self.pages[k])
        raise OSError("not found: " + url)
