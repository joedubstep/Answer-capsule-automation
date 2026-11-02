"""Turn kept homes into the engine's own file formats, exactly as the existing entries are built.

queue.json entry (surven_outreach/carehome.py reads id, email, facility, first_name, tz, rank, seq, emails;
day7 reads home; the A/B report reads variant), in the same key order as the 3,443 v3 entries:

  {"id", "email", "facility", "first_name", "tz", "rank", "variant", "seq": "v3", "home",
   "emails": {"1": {"subject", "body"}, "2": {"body"}, "3": {"pending": true}, "4": {"body"}}}

The copy is Joey's locked v3 (10/23), word for word as the queue has it:
  A, email 1: "Hi {first}, how many rooms are open at {home} right now?\\n\\nJoey"   (no name: "Hi, how many...")
  B, email 1: "Hi {first}, do you have any open rooms at {home} right now?\\n\\nJoey"
  email 2:    "Hey, I just emailed you.\\n\\nJoey"
  email 3:    {"pending": true}  (the engine builds day 7 at send time: free ad mockup or phone picture)
  email 4:    "Hi {first} I'm closing this out and will stop emailing.\\n\\nJoey" (no name: "I'm closing...")
  subject:    "Do you have an open room?"
Every body passes tools/copy_check (prospect_email) before it is written.
"""
import csv
import hashlib
import json
import os

from . import common

SUBJECT = "Do you have an open room?"
ASK = {"A": "how many rooms are open at {home} right now?", "B": "do you have any open rooms at {home} right now?"}
STEP2 = "Hey, I just emailed you.\n\nJoey"
FACT_KEYS = ["facility", "city", "state", "website", "website_source", "address", "beds", "beds_word", "care", "tz",
             "census", "open_beds", "census_date", "phone", "phone_source"]
QUEUE_KEYS = ["id", "email", "facility", "first_name", "tz", "rank", "variant", "seq", "home", "emails"]
REVIEW_COLS = ["decision", "reason", "id", "state", "license", "facility", "home", "home_check", "city", "county",
               "beds", "care", "status", "phone", "phone_source", "first_name", "first_name_source", "website",
               "website_source", "email", "email_source", "email_page", "emails_found", "variant", "rank",
               "copy_warnings"]


def bodies(first, home, variant):
    hi = f"Hi {first}, " if first else "Hi, "
    one = hi + ASK[variant].format(home=home) + "\n\nJoey"
    four = (f"Hi {first} I'm closing this out and will stop emailing.\n\nJoey" if first
            else "I'm closing this out and will stop emailing.\n\nJoey")
    return one, four


def queue_entry(rec, variant, rank):
    first, home = rec.get("first_name") or "", rec.get("home") or common.YOUR_HOME
    one, four = bodies(first, home, variant)
    return {
        "id": rec["id"],
        "email": rec["email"],
        "facility": rec["facility"],
        "first_name": first,
        "tz": rec["tz"],
        "rank": rank,
        "variant": variant,
        "seq": "v3",
        "home": home,
        "emails": {"1": {"subject": SUBJECT, "body": one}, "2": {"body": STEP2}, "3": {"pending": True},
                   "4": {"body": four}},
    }


def assign_variants(ids, mode="AB"):
    """Balanced and stable: order the batch by a hash of each id, then alternate A, B. mode 'A' or 'B' = all one."""
    if mode in ("A", "B"):
        return {i: mode for i in ids}
    order = sorted(ids, key=lambda i: hashlib.sha1(i.encode()).hexdigest())
    return {i: "AB"[n % 2] for n, i in enumerate(order)}


def assign_ranks(recs, min_rank):
    """Below every home already queued (the engine sends rank DESC, so the batch follows the current queue),
    bigger homes first inside the batch."""
    start = (min_rank if min_rank is not None else 0) - 1
    order = sorted(recs, key=lambda r: (-(r.get("beds") or 0), r["id"]))
    return {r["id"]: start - n for n, r in enumerate(order)}


def _check(text):
    try:
        from tools.copy_check.check import check
    except ImportError:  # the copy checker ships in this repo; a missing one must not pass copy silently
        raise SystemExit("tools.copy_check is missing: run from the Answer-capsule-automation repo root")
    return check(text, "prospect_email")


def copy_gate(rec, variant):
    """Run the copy checker on this home's emails 1 and 4. A blocking issue caused by the home's name falls back to
    "your home"; anything still blocking excludes the home. -> (ok, warnings list, note)."""
    note = ""
    for attempt in range(2):
        warns, blocks = [], []
        for text in bodies(rec.get("first_name") or "", rec.get("home") or common.YOUR_HOME, variant):
            res = _check(text)
            for i in res["issues"]:
                (blocks if i["severity"] == "block" else warns).append(i["rule"])
        if not blocks:
            return True, sorted(set(warns)), note
        if attempt == 0 and rec.get("home") != common.YOUR_HOME:
            note = f"copy check ({', '.join(sorted(set(blocks)))}) on the name, used 'your home'"
            rec["home"] = common.YOUR_HOME
            continue
        return False, sorted(set(warns)), f"copy check blocked: {', '.join(sorted(set(blocks)))}"
    return False, [], "copy check blocked"


def fact_entry(rec):
    return {
        "facility": rec["facility"], "city": rec["city"], "state": rec["state"],
        "website": rec.get("website", ""), "website_source": rec.get("website_source", ""),
        "address": rec["address"], "beds": rec["beds"], "beds_word": rec["beds_word"], "care": rec["care"],
        "tz": rec["tz"], "census": None, "open_beds": None, "census_date": "",
        "phone": rec.get("phone", ""), "phone_source": rec.get("phone_source", ""),
    }


def prospect_entry(rec, source, today):
    st, beds, city = rec["state"], rec["beds"], rec["city"]
    named = bool(rec.get("first_name"))
    sources = [f"{source.page_url} ({source.agency}, pulled {today})"]
    if (rec.get("email_page") or "").startswith("http"):
        sources.append(f"{rec['email_page']} (email found on this page, {today})")
    if (rec.get("website") or "").startswith("http"):
        sources.append(f"{rec['website']} (home's website: {rec.get('website_source', '')})")
    return {
        "id": rec["id"], "facility": rec["facility"], "website": rec.get("website", ""), "address": rec["address"],
        "state": st, "tz": rec["tz"], "care_type": f"{rec['care']} ({st} state license)", "beds": beds,
        "beds_source": f"{st} state license list: capacity {beds}",
        "private_pay": {"verified": [], "inferred": ["Licensed assisted living; private pay is the norm"],
                        "unknown": ["Rates", "Medicaid waiver share"]},
        "contact_name": common.nice_case(rec.get("admin_raw", "")) if named else "",
        "contact_role": (f"Administrator on the {st} license record (pulled {today})" if named else
                         f"No administrator on the {st} license record (pulled {today})") +
                        (f"; licensee: {rec['licensee']}" if rec.get("licensee") else ""),
        "email": rec["email"], "email_source": rec["email_source"],
        "email_confidence": f"{rec['email_source']}; check: nightly verify_mail before email 1",
        "bant": {
            "budget": {"verified": [], "inferred": [f"{beds}-bed licensed assisted living in {city}"],
                       "unknown": ["Rates", "Revenue"]},
            "authority": {"verified": [], "inferred": ["Administrator named on the state list" if named else
                                                       "Contact is likely the owner or administrator"],
                          "unknown": ["Final say on marketing spend"]},
            "need": {"verified": [], "inferred": [], "unknown": [f"Open beds ({st} publishes no census)"]},
            "timing": {"verified": [], "inferred": [], "unknown": ["Readiness to start"]},
        },
        "personalization": [f"{beds} licensed beds"],
        "status": "HOLD",
        "flags": [f"State list expansion {today} (lead_list tool), 40+ beds (Joey 10/23)"] + source.flags(rec),
        "reason": f"ICP fit ({beds} beds, licensed assisted living), open beds unknown, " +
                  ("named contact + email" if named else "email, no contact name"),
        "sources": sources,
        "researched": today,
    }


def build(recs, source, min_rank, today, variants="AB"):
    """recs: homes that passed filter, dedupe and have an email. -> (queue, facts, prospects); sets decision."""
    ranks = assign_ranks(recs, min_rank)
    var = assign_variants([r["id"] for r in recs], variants)
    queue, facts, people = [], {}, []
    for r in sorted(recs, key=lambda x: -ranks[x["id"]]):
        ok, warns, note = copy_gate(r, var[r["id"]])
        r["copy_warnings"] = "; ".join(warns)
        if note:
            r["home_check"] = (r.get("home_check") + "; " if r.get("home_check") else "") + note
        if not ok:
            r["decision"], r["reason"] = "exclude", note
            continue
        r["variant"], r["rank"] = var[r["id"]], ranks[r["id"]]
        r["decision"], r["reason"] = "include", "40+ beds, new to the campaign, published email"
        queue.append(queue_entry(r, r["variant"], r["rank"]))
        facts[r["id"]] = fact_entry(r)
        people.append(prospect_entry(r, source, today))
    return queue, facts, people


def write_json(path, obj, indent):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def write_review(path, recs):
    """utf-8 with a byte-order mark, so Excel on Joey's PC shows accented names right when he double-clicks it."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLS, extrasaction="ignore")
        w.writeheader()
        order = {"include": 0, "exclude": 1}
        for r in sorted(recs, key=lambda x: (order.get(x.get("decision"), 2), -(x.get("beds") or 0))):
            row = dict(r)
            row["emails_found"] = " ".join(r.get("emails_found") or [])
            w.writerow(row)
