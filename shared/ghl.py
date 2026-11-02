"""Read-mostly GoHighLevel client for cloud routines.

How auth works: each Claude cloud environment holds ONE GoHighLevel sub-account key, and the
Anthropic proxy adds it to every request to services.leadconnectorhq.com. So this module never
sends an Authorization header and never sees a key. Calls go through curl because Python HTTP
clients get blocked by Cloudflare on this host.

  Default env      -> American Golden Care (AGC)   location ySKGXQBLqevOlFCmV1Wo
  Surven HQ env    -> Surven HQ                    location EeadFhXhDOJ1DWE4ArhK
  Splendor env     -> Splendor Residence           location QxKf9rbHVJW6UvkFszds

Off-cloud tests set GHL_FAKE_DIR to a folder of canned JSON (see tests) so nothing hits the network.
"""
import json
import os
import subprocess
import time
import urllib.parse

BASE = "https://services.leadconnectorhq.com"
V_DEFAULT = "2021-07-28"
V_CONV = "2021-04-15"   # conversations, messages, calendars


def _fake(path, params):
    """Test hook: return canned JSON from GHL_FAKE_DIR keyed by a sanitized path."""
    d = os.environ.get("GHL_FAKE_DIR")
    if not d:
        return None
    key = path.strip("/").replace("/", "__") or "root"
    for name in (key + ".json",):
        p = os.path.join(d, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {"error": 404, "body": "no fake for " + key}


def call(path, params=None, ver=V_DEFAULT, method="GET", body=None, tries=4, timeout=60):
    """One API call. Returns parsed JSON, or {'error': code, 'body': text} on failure."""
    fake = _fake(path, params)
    if fake is not None:
        return fake
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    for i in range(tries):
        cmd = ["curl", "-s", "-m", str(timeout), "-X", method, "-w", "\n%{http_code}",
               "-H", "Version: " + ver, "-H", "Accept: application/json"]
        if data is not None:
            cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        cmd.append(url)
        try:
            p = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout + 30)
            out = p.stdout.decode("utf-8", "replace")
            txt, _, code = out.rpartition("\n")
            code = int(code) if code.strip().isdigit() else 0
        except Exception as e:  # noqa: BLE001
            code, txt = 0, str(e)
        if code in (200, 201):
            try:
                return json.loads(txt) if txt.strip() else {}
            except ValueError:
                code = 0
        if (code == 0 or code in (429, 500, 502, 503, 504)) and i < tries - 1:
            time.sleep(2 * (i + 1))
            continue
        return {"error": code or "net", "body": txt[:300]}
    return {"error": "net", "body": "retries exhausted"}


def ok(r):
    return isinstance(r, dict) and "error" not in r


def check_access(location_id):
    """First call of every run: True if this environment's key reads this location."""
    r = call("/contacts/", {"locationId": location_id, "limit": 1})
    return ok(r)


# ---------- paginated readers ----------

def opportunities(location_id, pipeline_id=None, status="all", max_pages=20):
    out, params = [], {"location_id": location_id, "limit": 100, "status": status}
    if pipeline_id:
        params["pipeline_id"] = pipeline_id
    for _ in range(max_pages):
        r = call("/opportunities/search", params)
        if not ok(r):
            return out if out else r
        batch = r.get("opportunities") or []
        out += batch
        meta = r.get("meta") or {}
        if len(batch) < 100 or not meta.get("startAfterId"):
            break
        params["startAfter"], params["startAfterId"] = meta.get("startAfter"), meta.get("startAfterId")
    return out


def pipelines(location_id):
    r = call("/opportunities/pipelines", {"locationId": location_id})
    return r.get("pipelines", []) if ok(r) else r


def contact(contact_id):
    r = call(f"/contacts/{contact_id}")
    return r.get("contact", r) if ok(r) else r


def search_contacts(location_id, filters=None, page_limit=100, max_pages=30):
    """POST /contacts/search (a read). filters: list of GHL filter dicts."""
    out, page = [], 1
    for _ in range(max_pages):
        body = {"locationId": location_id, "pageLimit": page_limit, "page": page}
        if filters:
            body["filters"] = filters
        r = call("/contacts/search", method="POST", body=body)
        if not ok(r):
            return out if out else r
        batch = r.get("contacts") or []
        out += batch
        if len(batch) < page_limit:
            break
        page += 1
    return out


def custom_fields(location_id):
    r = call(f"/locations/{location_id}/customFields")
    return r.get("customFields", []) if ok(r) else r


def field_map(location_id):
    """{field id: name} for this location's contact custom fields."""
    cf = custom_fields(location_id)
    return {f["id"]: f.get("name", "") for f in cf} if isinstance(cf, list) else {}


def conversations(location_id, contact_id=None, limit=100):
    params = {"locationId": location_id, "limit": limit, "sort": "desc", "sortBy": "last_message_date"}
    if contact_id:
        params["contactId"] = contact_id
    r = call("/conversations/search", params, ver=V_CONV)
    return r.get("conversations", []) if ok(r) else r


def messages(conversation_id, max_pages=5):
    out, last = [], None
    for _ in range(max_pages):
        params = {"limit": 100}
        if last:
            params["lastMessageId"] = last
        r = call(f"/conversations/{conversation_id}/messages", params, ver=V_CONV)
        if not ok(r):
            return out if out else r
        box = r.get("messages") or {}
        batch = box.get("messages") or []
        out += batch
        if not box.get("nextPage") or not batch:
            break
        last = box.get("lastMessageId") or batch[-1].get("id")
    return out


def calendar_events(location_id, calendar_id, start_ms, end_ms):
    r = call("/calendars/events", {"locationId": location_id, "calendarId": calendar_id,
                                   "startTime": int(start_ms), "endTime": int(end_ms)}, ver=V_CONV)
    return r.get("events", []) if ok(r) else r


def notes(contact_id):
    r = call(f"/contacts/{contact_id}/notes")
    return r.get("notes", []) if ok(r) else r


def custom_value(contact, field_id):
    for f in contact.get("customFields") or contact.get("customField") or []:
        if f.get("id") == field_id:
            v = f.get("value", f.get("field_value"))
            return v if v is not None else ""
    return ""
