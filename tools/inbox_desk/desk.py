"""Inbox Desk runner. Python does the searching plan, the sorting, the counting and the digest; the model only
moves connector results into files and writes the words.

Run from the repo root. Files live in /tmp/inbox_desk (INBOX_DESK_DIR to change it).

  python3 -m tools.inbox_desk.desk guard                       RUN at 8am or 4pm Eastern, else SKIP
  python3 -m tools.inbox_desk.desk start --mode scheduled|backlog [--max 25] [--dry-run]
        prints the Gmail searches to run; save each result to search/<n>.json
  python3 -m tools.inbox_desk.desk triage [--done-label-id Label_X]
        sorts what the searches found: which threads to read (fetch), which only get the Desk/Done label
  python3 -m tools.inbox_desk.desk classify                    reads threads/<id>.json -> work.json
  python3 -m tools.inbox_desk.desk skeletons                   drafts/<id>.txt from templates.md (+ plan facts files)
  python3 -m tools.inbox_desk.desk check                       copy check on every draft -> check.json (exit 1 = fix)
  python3 -m tools.inbox_desk.desk result <thread_id> <done> [--draft-id ID] [--note "..."] [--needs "..."]
  python3 -m tools.inbox_desk.desk digest                      digest.txt for Joey, or NO DIGEST
  python3 -m tools.inbox_desk.desk labels                      thread ids to label Desk/Done
"""
import argparse
import collections
import datetime as _dt
import json
import os
import re
import sys

from shared import et
from tools.inbox_desk import classify as cl
from tools.inbox_desk import drafts as dr
from tools.inbox_desk import settings as st

DIR = st.OUT_DIR
GUARD_HOURS = (8, 16)
PRIORITY = {("cold_reply", ""): 0, ("google_voice_text", "person"): 1, ("client", "message"): 2,
            ("vendor_or_data_sale", "person"): 3, ("vendor_or_data_sale", "system"): 4, ("coach", "email"): 5,
            ("coach", "call_recap"): 5, ("noise", "unknown_person"): 6, ("client", "automation_copy"): 7,
            ("google_voice_text", "own_line"): 8, ("automation_alert", "self"): 9,
            ("automation_alert", "lead_alert"): 9, ("noise", "bulk"): 10, ("noise", "ignored"): 10,
            ("noise", "sent"): 10}
READ_CLASSES = {("cold_reply", ""), ("google_voice_text", "person"), ("client", "message"),
                ("vendor_or_data_sale", "person"), ("vendor_or_data_sale", "system"), ("coach", "email"),
                ("coach", "call_recap"), ("noise", "unknown_person")}
DRAFT_DONE = ("drafted", "plan_drafted")
DONE_VALUES = ("drafted", "plan_drafted", "learning_saved", "summarized", "labeled", "no_action", "failed", "skipped")


def p(*parts):
    return os.path.join(DIR, *parts)


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def rules():
    return st.load_rules(private=p("private.json"))


# ---------------------------------------------------------------- guard

def guard(now=None, hours=GUARD_HOURS):
    return "RUN" if et.to_et(now or et.now_utc()).hour in hours else "SKIP"


# ---------------------------------------------------------------- start: the Gmail searches

def queries(mode, r, today=None, since=None):
    today = today or et.now_et().date()
    excl = "-label:" + (r.get("label_query") or "desk-done")
    cold = " OR ".join(r.get("cold_domains") or [])
    if mode == "backlog":
        after = (since or r.get("backlog_since") or "2026-09-23").replace("-", "/")
        return [{"name": "cold", "query": f"to:({cold}) -from:me {excl} after:{after}", "pages": 4}]
    after = (today - _dt.timedelta(days=int(r.get("window_days") or 3))).strftime("%Y/%m/%d")
    gv = r.get("google_voice") or {}
    voice = " OR ".join((gv.get("sender_domains") or []) + (gv.get("senders") or []))
    people = []
    for group in ("clients", "coaches", "vendors"):
        for ent in (r.get(group) or {}).values():
            people += list(ent.get("domains") or []) + list(ent.get("relay_domains") or []) + list(ent.get("senders") or [])
    people += list(r.get("coach_recap_senders") or [])
    people = sorted(set(x for x in people if x))
    out = [{"name": "cold", "query": f"to:({cold}) -from:me {excl} after:{after}", "pages": 1},
           {"name": "voice", "query": f"from:({voice}) {excl} after:{after}", "pages": 1}]
    if people:
        out.append({"name": "people", "query": f"from:({' OR '.join(people)}) {excl} after:{after}", "pages": 1})
    # The Primary tab. `category:primary` returns nothing through the Gmail connector (tested 2026-11-02), so it is
    # written as "in the inbox and in none of the other tabs".
    out.append({"name": "inbox", "query": f"in:inbox -from:me {PRIMARY_ONLY} {excl} after:{after}", "pages": 1})
    return out


PRIMARY_ONLY = "-category:promotions -category:social -category:updates -category:forums"


def drafts_query(mode, r, today=None, since=None):
    """Drafts made in the same window as the searches: a draft on a thread found now is never older than it."""
    today = today or et.now_et().date()
    if mode == "backlog":
        return "after:" + (since or r.get("backlog_since") or "2026-09-23").replace("-", "/")
    return "after:" + (today - _dt.timedelta(days=int(r.get("window_days") or 3))).strftime("%Y/%m/%d")


def cmd_start(a):
    r = rules()
    for sub in ("search", "threads", "drafts", "plans"):
        os.makedirs(p(sub), exist_ok=True)
    for sub in ("search", "threads", "drafts"):
        for f in os.listdir(p(sub)):
            os.unlink(p(sub, f))
    # every file a previous run in this session left behind, so a stale digest or draft list is never reused
    for f in ("triage.json", "work.json", "check.json", "results.json", "digest.txt", "digest.json",
              "drafts_existing.json", "state.json"):
        if os.path.exists(p(f)):
            os.unlink(p(f))
    mode = a.mode
    max_n = a.max or (40 if mode == "backlog" else int(r.get("max_threads") or 25))
    qs = queries(mode, r, since=a.since)
    dq = drafts_query(mode, r, since=a.since)
    state = {"mode": mode, "dry_run": a.dry_run, "max": max_n, "started_et": et.now_et().strftime("%Y-%m-%d %H:%M"),
             "label": r.get("label"), "queries": qs, "drafts_query": dq}
    save(p("state.json"), state)
    print(f"Inbox Desk {mode}{' (dry run)' if a.dry_run else ''}: up to {max_n} threads. Label: {r.get('label')}")
    if not r.get("booking_link"):
        print("WARNING: no booking link in config/surven.json (inbox_desk.booking_link). Drafts that need it will be "
              "held by the copy checker. Say so in the digest.")
    print("Run each search with search_threads (view THREAD_VIEW_SUMMARY, pageSize 50) and save the raw result to "
          f"{p('search')}/<name>-<page>.json:")
    for q in qs:
        print(f"  {q['name']} (up to {q['pages']} page{'s' if q['pages'] > 1 else ''}): {q['query']}")
    print(f"Also: list_drafts (query \"{dq}\", pageSize 50). Write ONLY the thread ids, as a JSON list like "
          f"[\"<threadId>\", ...], to {p('drafts_existing.json')} (skips threads that already have a draft).")
    if r.get("notion", {}).get("inbox_desk_settings"):
        print(f"Private senders: fetch Notion page {r['notion']['inbox_desk_settings']}, save its text to "
              f"{p('settings.md')}, then run: python3 -m tools.inbox_desk.settings --from-text {p('settings.md')}")
    return 0


# ---------------------------------------------------------------- triage (headers only)

def _search_threads():
    out = []
    d = p("search")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            out += cl.threads_in(load(os.path.join(d, f), {}) or {})
    seen, uniq = set(), []
    for t in out:
        if t.get("id") and t["id"] not in seen:
            seen.add(t["id"])
            uniq.append(t)
    return uniq


def _draft_threads():
    """Thread ids that already have a draft: a plain list of ids, or the raw list_drafts result."""
    d = load(p("drafts_existing.json"), {}) or {}
    items = d.get("drafts") if isinstance(d, dict) else d
    out = set()
    for x in items or []:
        if isinstance(x, str):
            out.add(x)
        elif isinstance(x, dict):
            out.add(x.get("threadId") or x.get("thread_id") or (x.get("message") or {}).get("threadId"))
    return out - {None, ""}


def triage(threads, r, max_n=25, done_label_id=None, draft_threads=()):
    rows = []
    for t in threads:
        nt = cl.norm_thread(t)
        if not nt["messages"]:
            continue
        last = nt["messages"][-1]
        labels = set(sum((m["labels"] for m in nt["messages"]), []))
        if done_label_id and done_label_id in labels:
            continue
        inbound = [m for m in nt["messages"] if not cl.is_own(m["sender"], r)]
        msg = inbound[-1] if inbound else last
        c, s, why, _ = cl.header_class(msg, r)
        row = {"id": nt["id"], "class": c, "sub": s, "reason": why, "from_domain": cl.domain_of(msg["sender"]),
               "subject": (msg["subject"] or "")[:60], "date": msg["date"]}
        key = (c, s)
        if cl.is_own(last["sender"], r) and last is not msg or (not inbound and nt["count"] > 1):
            row["reason"], row["act"] = "Joey already replied", "label"
        elif c == "cold_reply" and (re.search((r.get("auto_reply") or {}).get("subject") or r"$^", msg["subject"] or "", re.I)
                                    or re.search((r.get("auto_reply") or {}).get("sender_local") or r"$^",
                                                 msg["sender"].split("@")[0], re.I)):
            row["sub"], row["reason"], row["act"] = "auto_reply", "auto-reply (subject or sender)", "label"
        elif nt["id"] in draft_threads:
            row["reason"], row["act"] = "a draft is already waiting", "skip"
        elif key == ("vendor_or_data_sale", "system") and not re.search(
                r.get("vendor_action_subject") or r"$^", msg["subject"] or "", re.I):
            row["reason"], row["act"] = "vendor newsletter or notice, nothing to do", "label"
        else:
            row["act"] = "read" if key in READ_CLASSES else "label"
        row["prio"] = PRIORITY.get(key, 10)
        rows.append(row)
    rows.sort(key=lambda x: (x["prio"], x["date"]))
    work = [x for x in rows if x["act"] != "skip"]
    take, waiting = work[:max_n], work[max_n:]
    return {"fetch": [x for x in take if x["act"] == "read"], "label_only": [x for x in take if x["act"] == "label"],
            "skipped": [x for x in rows if x["act"] == "skip"], "waiting": len(waiting), "found": len(rows),
            "counts": dict(collections.Counter(x["class"] + ("/" + x["sub"] if x["sub"] else "") for x in take))}


def cmd_triage(a):
    r = rules()
    state = load(p("state.json"), {}) or {}
    res = triage(_search_threads(), r, a.max or state.get("max") or 25, a.done_label_id, _draft_threads())
    res["mode"] = state.get("mode", "scheduled")
    save(p("triage.json"), res)
    if not res["fetch"] and not res["label_only"]:
        print(f"NOTHING NEW ({res['found']} thread(s) found, all handled already)")
        return 0
    print(f"triage: {res['found']} found. Read {len(res['fetch'])}, label only {len(res['label_only'])}, "
          f"already drafted {len(res['skipped'])}, waiting for the next run {res['waiting']}.")
    if res["fetch"]:
        print(f"READ each with get_thread (messageFormat PLAIN_TEXT) and save the raw result to {p('threads')}/<id>.json:")
        for x in res["fetch"]:
            print(f"  {x['id']}  {x['class']}{'/' + x['sub'] if x['sub'] else ''}  {x['from_domain']}")
    if res["label_only"]:
        c = collections.Counter(x["class"] + ("/" + x["sub"] if x["sub"] else "") for x in res["label_only"])
        print("LABEL ONLY: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    return 0


# ---------------------------------------------------------------- classify (full threads)

def build_work(tri, r, threads_dir):
    items = []
    for x in tri.get("fetch") or []:
        raw = load(os.path.join(threads_dir, x["id"] + ".json"))
        ts = cl.threads_in(raw) if raw else []
        if not ts:
            items.append({"thread_id": x["id"], "class": x["class"], "sub": x["sub"], "action": "not_read",
                          "reasons": ["thread file missing: it was not read, so it is not labeled"],
                          "from_domain": x.get("from_domain", ""), "needs_joey": False})
            continue
        it = cl.classify_thread(ts[0], r)
        it["date_utc"] = (cl.latest_inbound(cl.norm_thread(ts[0]), r) or {}).get("date", "")
        items.append(it)
    for x in tri.get("label_only") or []:
        items.append({"thread_id": x["id"], "class": x["class"], "sub": x["sub"], "action": "label_only",
                      "reasons": [x["reason"]], "from_domain": x.get("from_domain", ""), "needs_joey": False})
    return items


_HOME_STOP = re.compile(r"^(?:at|of|in|on|by|assisted|senior|memory|living|care|llc|inc|the)$", re.I)


def short_home(name):
    """'Maple Terrace At Sampletown' -> 'Maple Terrace'; 'The Example House' -> 'Example House'."""
    words = [w for w in re.split(r"\s+", (name or "").strip()) if w]
    if words and words[0].lower() == "the" and len(words) > 1:
        words = words[1:]
    out = []
    for w in words:
        if out and _HOME_STOP.match(w):
            break
        out.append(w)
        if len(out) == 3:
            break
    return " ".join(out)


def who(it):
    g = it.get("ghl") or {}
    return g.get("code") or short_home(it.get("home")) or it.get("label") or it.get("from_domain") or it["thread_id"]


def cmd_classify(a):
    r = rules()
    tri = load(p("triage.json"))
    if not tri:
        print("no triage.json: run desk triage first")
        return 2
    items = build_work(tri, r, p("threads"))
    save(p("work.json"), {"mode": tri.get("mode"), "generated_et": et.now_et().strftime("%Y-%m-%d %H:%M"),
                          "booking_link_set": bool(r.get("booking_link")), "items": items})
    acts = collections.Counter(it["action"] for it in items)
    print("work: " + ", ".join(f"{k} {v}" for k, v in sorted(acts.items())))
    n = 0
    for it in items:
        if it["action"] in ("label_only",):
            continue
        n += 1
        head = f"{n}. {it['thread_id']}  {it['class']}{'/' + it['sub'] if it.get('sub') else ''}  -> {it['action']}"
        extra = []
        if it.get("home"):
            extra.append(f"home: {it['home']} ({it.get('home_source')})")
        if it.get("first"):
            extra.append(f"first: {it['first']} ({it.get('first_source')})")
        if it.get("rooms") is not None:
            extra.append(f"rooms: {it['rooms']}")
        if it.get("class") == "cold_reply" and it.get("offer") not in (None, "", "unknown"):
            extra.append(f"offer: {it['offer']}")  # the email they answered (plan = the plan was already offered)
        if it.get("confidence") and it["confidence"] != "high":
            extra.append(f"confidence {it['confidence']}: {'; '.join(it.get('reasons', [])[-1:])}")
        if it.get("reply_mode"):
            extra.append(f"reply: {it['reply_mode']}")
        print(head + ("\n     " + " | ".join(extra) if extra else ""))
        if it.get("text"):
            print("     said: " + re.sub(r"\s+", " ", it["text"])[:220])
        if it.get("learning"):
            print("     learning row: " + json.dumps(it["learning"]))
    return 0


# ---------------------------------------------------------------- skeletons and check

def cmd_skeletons(a):
    r = rules()
    work = load(p("work.json"))
    if not work:
        print("no work.json: run desk classify first")
        return 2
    tpl = dr.parse_templates()
    os.makedirs(p("drafts"), exist_ok=True)
    os.makedirs(p("plans"), exist_ok=True)
    n = 0
    for it in work["items"]:
        if it["action"] not in ("draft_reply", "draft_plan"):
            continue
        text = dr.skeleton(it, tpl, r.get("booking_link"))
        if not text:
            continue
        path = p("drafts", it["thread_id"] + ".txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        n += 1
        line = f"  {path}  ({it['template']}, {it['copy_context']}{', link required' if it.get('require_link') else ''})"
        to = it.get("reply_to") or "(no To line: copy into GoHighLevel)"
        line += f"\n     create_draft: replyToMessageId={it.get('message_id')} to={to} subject={it.get('reply_subject')!r}"
        if it["action"] == "draft_plan":
            fp = p("plans", it["thread_id"] + ".facts.json")
            if not os.path.exists(fp):
                save(fp, {"home": it.get("home") or "", "city": "", "state": "",
                          "beds": {"value": None, "source": ""}, "care_type": {"value": "", "source": ""}})
            line += f"\n     plan facts: {fp}"
        print(line)
    print(f"skeletons: {n} draft(s) written. Edit each to fit the reply, then run desk check.")
    return 0


def cmd_check(a):
    work = load(p("work.json"))
    if not work:
        print("no work.json")
        return 2
    out, blocked = {}, 0
    for it in work["items"]:
        path = p("drafts", it["thread_id"] + ".txt")
        if it["action"] not in ("draft_reply", "draft_plan") or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        res = dr.check(text, it.get("copy_context") or "prospect_email", bool(it.get("require_link")))
        if re.search(r"\{(?:greeting|home|booking_link|first|answer[^}]*|the answer[^}]*)\}", text):
            res["ok"] = False
            res["blocking"].append({"rule": "template_blank", "match": "{...}", "line": 0,
                                    "fix": "Fill in or delete the template blank."})
        out[it["thread_id"]] = res
        if not res["ok"]:
            blocked += 1
        status = "ok" if res["ok"] else "BLOCKED"
        print(f"  {it['thread_id']}  {status}  grade {res.get('grade')}"
              + "".join(f"\n     BLOCK {b['rule']}: {b['match']!r} -> {b['fix']}" for b in res["blocking"])
              + "".join(f"\n     warn {w['rule']}: {w['match']!r}" for w in res["warnings"][:4]))
    save(p("check.json"), out)
    print(f"check: {len(out)} draft(s), {blocked} blocked")
    return 1 if blocked else 0


# ---------------------------------------------------------------- results, digest, labels

def cmd_result(a):
    res = load(p("results.json"), {}) or {}
    if a.done not in DONE_VALUES:
        print(f"done must be one of: {', '.join(DONE_VALUES)}")
        return 2
    ent = {"done": a.done}
    for k in ("draft_id", "note", "needs"):
        v = getattr(a, k)
        if v:
            ent[k] = v.strip()[:200]
    res[a.thread_id] = ent
    save(p("results.json"), res)
    print(f"result: {a.thread_id} {a.done}")
    return 0


WHAT = {
    "vacancy_or_family_misread": "thought you were a family. Draft clears it up and offers the plan",
    "asked_for_plan": "asked for the plan. Draft has the plan PDF attached",
    "question_what_is_this": "asked who you are. Draft answers and offers the plan",
    "interested_call": "wants to talk. Draft sends your booking link",
    "not_interested_or_full": "is full. Draft closes it kindly",
    "wrong_person_or_referral": "pointed you to someone else. Draft asks who",
}


def digest(work, results, joey):
    items = work.get("items") or []
    drafts, needs, learn = [], [], []
    for it in items:
        res = results.get(it["thread_id"]) or {}
        done = res.get("done")
        name = who(it)
        if done in DRAFT_DONE:
            if it["class"] == "cold_reply":
                tag = name + (" plan" if it.get("sub") == "asked_for_plan" else "")
                line = f"{name}: {WHAT.get(it.get('sub'), 'replied')}."
                if it.get("cold_to"):
                    line += f" Send it from {it['cold_to']}."
            elif it["class"] == "google_voice_text":
                tag, line = "text", "A text to your Google Voice. Sending the draft texts them back."
            elif it["class"] == "client" and it.get("reply_mode") == "copy_to_ghl":
                tag = None
                needs.append(f"{it.get('label') or 'Client'} mail: reply drafted in the thread with no To line. "
                             "Copy it into the conversation in GoHighLevel.")
                line = None
            elif it["class"] == "client":
                tag, line = (it.get("label") or "client"), f"{it.get('label') or 'Client'} mail: reply drafted."
            else:
                tag, line = (it.get("label") or name), f"{it.get('label') or name}: reply drafted from the Answer Bank."
            if tag:
                drafts.append((tag, line + (" " + res["note"] if res.get("note") else "")))
        elif done == "learning_saved":
            learn.append(it.get("label") or name)
        if it.get("cleanup"):
            needs.append(it["cleanup"])
        elif it.get("sub") == "opt_out" and not (it.get("ghl") or {}).get("found") and done != "failed":
            pass  # no GHL access or no contact: nothing to clean that we know of
        if res.get("needs"):
            needs.append(f"{name}: {res['needs']}")
        elif done == "summarized" and it.get("needs_joey"):
            needs.append(f"{name}: {res.get('note') or 'have a look'}")
        if done == "failed":
            needs.append(f"{name}: the desk could not finish this one ({res.get('note') or 'see the run'}).")
    if not work.get("booking_link_set") and any(it.get("require_link") for it in items):
        needs.append("Add the booking link to config/surven.json (inbox_desk.booking_link). Drafts that need it were held.")
    if not drafts and not needs:
        return None
    tags = [t for t, _ in drafts]
    subj = "Inbox Desk: "
    if drafts:
        shown = ", ".join(tags[:3]) + (f" and {len(tags) - 3} more" if len(tags) > 3 else "")
        subj += f"{len(drafts)} draft{'s' if len(drafts) != 1 else ''} ready ({shown})"
    if needs:
        subj += (", " if drafts else "") + f"{len(needs)} need{'s' if len(needs) == 1 else ''} you"
    body = []
    if drafts:
        body.append("Drafts ready in Gmail. Open each one, check it, then send:")
        body += [f"- {line}" for _, line in drafts]
    if needs:
        body += ([""] if body else []) + ["Needs you:"] + [f"- {n}" for n in needs]
    if learn:
        c = collections.Counter(learn)
        body += ["", "Saved to Learnings: " + ", ".join(f"{k}" + (f" ({v})" if v > 1 else "") for k, v in c.items()) + "."]
    waiting = work.get("waiting") or 0
    if waiting:
        body += ["", f"{waiting} more email(s) wait for the next run."]
    return {"to": joey, "subject": subj[:180], "body": "\n".join(body).strip() + "\n"}


def cmd_digest(a):
    r = rules()
    work = load(p("work.json"))
    if not work:
        print("NO DIGEST (no work.json)")
        return 0
    tri = load(p("triage.json"), {}) or {}
    work["waiting"] = tri.get("waiting", 0)
    d = digest(work, load(p("results.json"), {}) or {}, r.get("joey_gmail"))
    if not d:
        for f in ("digest.txt", "digest.json"):
            if os.path.exists(p(f)):
                os.unlink(p(f))
        print("NO DIGEST (nothing new needs Joey)")
        return 0
    if not d["to"] or "@" not in d["to"]:
        print("NO DIGEST (config google.joey_gmail is missing)")
        return 1
    chk = dr.check(d["subject"] + "\n" + d["body"], "internal")
    with open(p("digest.txt"), "w", encoding="utf-8") as f:
        f.write(f"To: {d['to']}\nSubject: {d['subject']}\n\n{d['body']}")
    save(p("digest.json"), d)
    if (load(p("state.json"), {}) or {}).get("dry_run"):
        print("DRY RUN: do not send this digest. It is shown only so Joey can check it.")
    print(f"DIGEST to {d['to']}: {d['subject']}")
    print(d["body"])
    if not chk["ok"]:
        print("copy check: " + "; ".join(f"{b['rule']} {b['match']!r}" for b in chk["blocking"]))
    return 0


def cmd_labels(a):
    work = load(p("work.json"), {}) or {}
    results = load(p("results.json"), {}) or {}
    ids = []
    for it in work.get("items") or []:
        if it["action"] == "not_read":
            continue
        done = (results.get(it["thread_id"]) or {}).get("done")
        if it["action"] == "label_only" or done in DONE_VALUES and done != "failed":
            ids.append(it["thread_id"])
    if (load(p("state.json"), {}) or {}).get("dry_run"):
        print(f"DRY RUN: do not label. {len(ids)} thread(s) would get the Desk/Done label.")
        return 0
    print("\n".join(ids) if ids else "(none)")
    return 0


def main(argv=None):
    global DIR
    ap = argparse.ArgumentParser(description="Inbox Desk runner")
    ap.add_argument("--dir", default=None, help="working folder (default /tmp/inbox_desk)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("guard")
    g.add_argument("--hours", default="8,16")
    s = sub.add_parser("start")
    s.add_argument("--mode", choices=("scheduled", "backlog"), default="scheduled")
    s.add_argument("--max", type=int)
    s.add_argument("--since")
    s.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("triage")
    t.add_argument("--done-label-id")
    t.add_argument("--max", type=int)
    sub.add_parser("classify")
    sub.add_parser("skeletons")
    sub.add_parser("check")
    rs = sub.add_parser("result")
    rs.add_argument("thread_id")
    rs.add_argument("done")
    rs.add_argument("--draft-id")
    rs.add_argument("--note")
    rs.add_argument("--needs")
    sub.add_parser("digest")
    sub.add_parser("labels")
    a = ap.parse_args(argv)
    if a.dir:
        DIR = a.dir
    if a.cmd == "guard":
        print(guard(hours=tuple(int(h) for h in a.hours.split(","))))
        return 0
    return {"start": cmd_start, "triage": cmd_triage, "classify": cmd_classify, "skeletons": cmd_skeletons,
            "check": cmd_check, "result": cmd_result, "digest": cmd_digest, "labels": cmd_labels}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
