"""Read a state license download (CSV, TXT, XLSX, JSON, an HTML-table "Excel" export or an Excel 2003 XML file)
with the standard library only, and map its headers.

States rename columns between releases, so each source module lists ALIASES per field and this module finds the
header row that matches the most of them. `inspect` (run.py) prints the mapping so a builder can see in one look
whether a column moved, and fix the alias list instead of the code.
"""
import csv
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def hkey(s):
    """Header key: 'Licensed Beds #' -> 'licensedbeds'."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _decode(data):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "A").group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def xlsx_matrix(data, sheet=0):
    """First (or nth) worksheet of an .xlsx as a list of rows (lists of strings)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = wb.findall("m:sheets/m:sheet", NS)
    path = "xl/worksheets/sheet1.xml"
    if sheets and "xl/_rels/workbook.xml.rels" in z.namelist():
        rid = sheets[min(sheet, len(sheets) - 1)].get("{%s}id" % REL_NS)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for r in rels:
            if r.get("Id") == rid:
                target = r.get("Target").lstrip("/")
                path = target if target.startswith("xl/") else "xl/" + target
    root = ET.fromstring(z.read(path))
    rows = []
    for row in root.iter("{%s}row" % NS["m"]):
        vals = {}
        nxt = 0  # some generators leave out the cell reference ("r"): then cells sit in order
        for c in row.findall("m:c", NS):
            t = c.get("t")
            v = c.find("m:v", NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif v is not None:
                val = v.text or ""
                if re.match(r"^-?\d+\.0+$", val):
                    val = val.split(".")[0]
            else:
                val = ""
            ci = _col_index(c.get("r")) if c.get("r") else nxt
            vals[ci] = val.strip()
            nxt = ci + 1
        if vals:
            width = max(vals) + 1
            rows.append([vals.get(i, "") for i in range(width)])
    return rows


class _Tables(HTMLParser):
    """Every <table> in a page as a list of rows. Many state sites' "Export to Excel" buttons send an HTML table
    with an .xls name, which Excel opens without complaint."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append({"rows": [], "row": None, "cell": None})
        elif not self._stack:
            return
        elif tag == "tr":
            t = self._stack[-1]
            t["row"] = []
            t["rows"].append(t["row"])
        elif tag in ("td", "th"):
            t = self._stack[-1]
            if t["row"] is None:
                t["row"] = []
                t["rows"].append(t["row"])
            t["cell"] = []
            t["row"].append(t["cell"])
            span = dict(attrs).get("colspan") or "1"
            for _ in range(min(int(span) if span.isdigit() else 1, 50) - 1):
                t["row"].append([])
        elif tag == "br" and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append("\n")

    def handle_endtag(self, tag):
        if not self._stack:
            return
        if tag == "table":
            t = self._stack.pop()
            self.tables.append([[re.sub(r"[ \t\r\f\v]+", " ", "".join(c)).strip() for c in r] for r in t["rows"]])
        elif tag in ("td", "th"):
            self._stack[-1]["cell"] = None
        elif tag == "tr":
            self._stack[-1]["row"] = None

    def handle_data(self, data):
        if self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append(data)


def html_matrix(text):
    """The biggest table in an HTML page (by row count) -> rows. [] when the page has no table."""
    p = _Tables()
    p.feed(text)
    p.close()
    tables = [t for t in p.tables if t]
    return max(tables, key=len) if tables else []


def spreadsheetml_matrix(text):
    """Excel 2003 XML ("XML Spreadsheet"), another common export format. First worksheet only."""
    ns = "urn:schemas-microsoft-com:office:spreadsheet"
    root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text))  # already decoded: drop the encoding line
    ws = root.find(f"{{{ns}}}Worksheet")
    rows = []
    for row in (ws.iter(f"{{{ns}}}Row") if ws is not None else []):
        vals, i = {}, 0
        for cell in row.findall(f"{{{ns}}}Cell"):
            idx = cell.get(f"{{{ns}}}Index")
            i = int(idx) - 1 if idx and idx.isdigit() else i
            d = cell.find(f"{{{ns}}}Data")
            vals[i] = ("".join(d.itertext()) if d is not None else "").strip()
            i += 1
        rows.append([vals.get(k, "") for k in range(max(vals) + 1)] if vals else [])
    return rows


def text_matrix(text):
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        delim = dialect.delimiter
    except csv.Error:
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]


def json_records(text):
    d = json.loads(text)
    if isinstance(d, dict):
        for k in ("data", "records", "results", "features", "items", "rows", "value"):
            if isinstance(d.get(k), list):
                d = d[k]
                break
    if not isinstance(d, list):
        raise ValueError("JSON file holds no list of records")
    out = []
    for r in d:
        if isinstance(r, dict) and isinstance(r.get("attributes"), dict):  # ArcGIS feature
            r = r["attributes"]
        if isinstance(r, dict):
            out.append({str(k): ("" if v is None else str(v)).strip() for k, v in r.items()})
    return out


def read_matrix(path_or_bytes, name=""):
    """-> (kind, rows) where kind is 'matrix' (list of lists) or 'records' (list of dicts, from JSON)."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        name = name or str(path_or_bytes)
        with open(path_or_bytes, "rb") as f:
            data = f.read()
    low = name.lower()
    if data[:2] == b"PK" or low.endswith(".xlsx"):
        return "matrix", xlsx_matrix(data)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("old binary .xls file: open it and save as .xlsx or .csv, then pass that file")
    text = _decode(data)
    head = text.lstrip()[:1]
    if not head:
        raise ValueError("the file is empty")
    if low.endswith(".json") or head in ("[", "{"):
        return "records", json_records(text)
    start = text[:5000].lower()
    if "urn:schemas-microsoft-com:office:spreadsheet" in start:
        return "matrix", spreadsheetml_matrix(text)
    if "<table" in text.lower():
        rows = html_matrix(text)
        if len(rows) > 1:
            return "matrix", rows
    if "<html" in start or "<!doctype html" in start:
        raise ValueError("this is a web page with no data table (the download link probably needs a browser)")
    return "matrix", text_matrix(text)


def map_headers(headers, aliases):
    """{field: column header} for each field whose alias matches a header (first alias wins)."""
    keyed = {}
    for h in headers:
        k = hkey(h)
        if k and k not in keyed:
            keyed[k] = h
    out = {}
    for field, names in aliases.items():
        for a in names:
            if hkey(a) in keyed:
                out[field] = keyed[hkey(a)]
                break
    return out


def find_header(matrix, aliases, scan=25):
    """Index of the row (within the first `scan`) that matches the most aliases; title rows above it are skipped."""
    best, best_n = 0, -1
    for i, row in enumerate(matrix[:scan]):
        n = len(map_headers(row, aliases))
        if n > best_n:
            best, best_n = i, n
    return best


def load_rows(path_or_bytes, aliases, name=""):
    """-> (headers, mapping, rows as dicts keyed by the original headers)."""
    kind, data = read_matrix(path_or_bytes, name)
    if kind == "records":
        headers = list(dict.fromkeys(k for r in data for k in r))
        return headers, map_headers(headers, aliases), data
    if not data:
        return [], {}, []
    hi = find_header(data, aliases)
    headers = [h or f"col{i + 1}" for i, h in enumerate(data[hi])]
    rows = []
    for r in data[hi + 1:]:
        if not any(c.strip() for c in r):
            continue
        rows.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
    return headers, map_headers(headers, aliases), rows
