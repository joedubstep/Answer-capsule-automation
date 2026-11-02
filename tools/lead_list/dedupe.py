"""Keep homes the campaign already has out of a new batch.

Matches against everything the engine knows (carehome.db prospects of every status, lead_facts.json, queue.json and
build/prospects.json) by: the same campaign id, the same license or file number in the same state, the same
name and city, the same phone, or the same email address. carehome.db is opened read-only
(sqlite 'file:...?mode=ro'); it is cloud-owned and this tool never writes it.
"""
import json
import os
import sqlite3

from . import common


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _city_from_address(addr):
    parts = [p.strip() for p in (addr or "").split(";")[0].split(",")]
    return parts[-2] if len(parts) >= 3 else ""


class Index:
    def __init__(self):
        self.ids = set()
        self.license = {}      # (state, token) -> id
        self.name_city = {}    # (state, name key, city key) -> id
        self.phone = {}        # +1... -> id
        self.email = {}        # address -> id
        self.counts = {}
        self.min_rank = None

    # ---- building ----
    def add(self, pid, state="", facility="", city="", phone="", email=""):
        pid = (pid or "").strip()
        st = (state or pid.split("-")[0]).strip().lower()
        if pid:
            self.ids.add(pid)
            tok = common.id_license_token(pid)
            if tok:
                self.license.setdefault((st, tok), pid)
        if facility and city:
            self.name_city.setdefault((st, common.norm_name(facility), common.norm_city(city)), pid)
        ph = common.phone_e164(phone) if phone and not str(phone).startswith("+") else (phone or "")
        if ph:
            self.phone.setdefault(ph, pid)
        e = (email or "").strip().lower()
        if e:
            self.email.setdefault(e, pid)

    @classmethod
    def load(cls, data_dir):
        """Read the engine's state folder (data/carehome). Missing files are skipped and counted as 0."""
        ix = cls()
        facts = _load_json(os.path.join(data_dir, "lead_facts.json"), {})
        queue = _load_json(os.path.join(data_dir, "queue.json"), [])
        people = _load_json(os.path.join(data_dir, "build", "prospects.json"), [])
        for pid, f in facts.items():
            ix.add(pid, f.get("state", ""), f.get("facility", ""), f.get("city", ""), f.get("phone", ""))
        for p in queue:
            f = facts.get(p.get("id"), {})
            ix.add(p.get("id"), "", p.get("facility", ""), f.get("city", ""), "", p.get("email", ""))
            r = p.get("rank")
            if isinstance(r, int):
                ix.min_rank = r if ix.min_rank is None else min(ix.min_rank, r)
        for p in people:
            ix.add(p.get("id"), p.get("state", ""), p.get("facility", ""), _city_from_address(p.get("address")),
                   "", p.get("email", ""))
        db_n = 0
        db = os.path.join(data_dir, "carehome.db")
        if os.path.exists(db):
            con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
            try:
                for pid, email, facility in con.execute("SELECT id, email, facility FROM prospects"):
                    f = facts.get(pid, {})
                    ix.add(pid, "", facility or "", f.get("city", ""), "", email or "")
                    db_n += 1
            finally:
                con.close()
        ix.counts = {"carehome.db prospects": db_n, "lead_facts.json": len(facts), "queue.json": len(queue),
                     "build/prospects.json": len(people), "ids": len(ix.ids), "phones": len(ix.phone),
                     "emails": len(ix.email)}
        return ix

    # ---- matching ----
    def match(self, rec, email=""):
        """-> '' when new, else why it is a duplicate (names the existing campaign id)."""
        st = rec.get("state", "").lower()
        if rec.get("id") in self.ids:
            return f"already in the campaign (same id {rec['id']})"
        tok = common.license_token(rec.get("license"))
        if tok and (st, tok) in self.license:
            return f"already in the campaign (same license number as {self.license[(st, tok)]})"
        key = (st, common.norm_name(rec.get("official_name") or rec.get("facility")), common.norm_city(rec.get("city")))
        if key[1] and key[2] and key in self.name_city:
            return f"already in the campaign (same name and city as {self.name_city[key]})"
        if rec.get("phone") and rec["phone"] in self.phone:
            return f"already in the campaign (same phone as {self.phone[rec['phone']]})"
        e = (email or "").strip().lower()
        if e and e in self.email:
            return f"already in the campaign (same email as {self.email[e]})"
        return ""

    def remember(self, rec, email=""):
        """Add a kept batch home so later rows in the same batch dedupe against it."""
        self.add(rec.get("id"), rec.get("state", ""), rec.get("official_name") or rec.get("facility"),
                 rec.get("city", ""), rec.get("phone", ""), email)


def apply(index, recs):
    """Pass 1 (before the web step): drop homes already in the campaign or repeated in the batch, by id, license,
    name + city and phone. Bigger homes win a tie inside the batch. Emails are checked again after the email step."""
    batch, kept = Index(), []
    for r in sorted(recs, key=lambda x: -(x.get("beds") or 0)):
        why = index.match(r) or batch.match(r).replace("already in the campaign", "repeated in this batch")
        if why:
            r["decision"], r["reason"] = "exclude", why
            continue
        batch.remember(r)
        kept.append(r)
    return kept


def apply_email(index, recs):
    """Pass 2 (after the email step): one address never gets two homes' emails, and never one the campaign used."""
    kept, seen = [], {}
    for r in sorted(recs, key=lambda x: -(x.get("beds") or 0)):
        e = (r.get("email") or "").lower()
        if not e:
            kept.append(r)
            continue
        if e in seen:
            r["decision"], r["reason"] = "exclude", f"same email as {seen[e]} in this batch (bigger home kept)"
            continue
        prior = index.email.get(e)
        if prior and prior != r.get("id"):
            r["decision"], r["reason"] = "exclude", f"already in the campaign (same email as {prior})"
            continue
        seen[e] = r["id"]
        kept.append(r)
    return kept
