"""Deterministic pre-classification of a Gmail thread (the JSON the Gmail connector returns).

Classes
  cold_reply          a reply to Joey's cold email (sent to joey@<cold email domain>), with a sub-class:
                      vacancy_or_family_misread | asked_for_plan | question_what_is_this | interested_call |
                      not_interested_or_full | opt_out | wrong_person_or_referral | auto_reply
  google_voice_text   a Google Voice text, voicemail or missed call forward (sub: person | own_line)
  client              mail from a client home (AGC, Splendor, the legacy client) (sub: message | automation_copy)
  coach               coach mail worth a Learnings row (Senior Living Mastery, Acquisition.com, Lead Suite, ...)
  vendor_or_data_sale data buyers and vendors (SimpleClosure, Polyshares, DataVendor, ...) (sub: person | system)
  automation_alert    Joey's own plan emails, the morning brief, data-sale alerts, lead/booking alerts
  noise               everything else (sub: bulk | unknown_person | ignored)

The model never re-does this. It reads the result and only writes (drafts, Learnings rows, the digest).

  python3 -m tools.inbox_desk.classify <thread.json> [...] [--private /tmp/inbox_desk/private.json] [--json]
Each file may hold one get_thread result, a search_threads result ({"threads": [...]}) or a list of threads.
Prints one line per thread and the class counts (no addresses, no message text unless --json).
"""
import argparse
import collections
import json
import os
import re
import sys

from shared import et
from tools.inbox_desk import settings as st
from tools.inbox_desk import textutil as tu

SUBCLASSES = ("vacancy_or_family_misread", "asked_for_plan", "question_what_is_this", "interested_call",
              "not_interested_or_full", "opt_out", "wrong_person_or_referral", "auto_reply")
CLASSES = ("cold_reply", "google_voice_text", "client", "coach", "vendor_or_data_sale", "automation_alert", "noise")

# ---------------------------------------------------------------- reply meaning (cold replies)
I = re.I
_STRONG_REFERRAL = re.compile(
    r"\b(no longer (with|works|working|employed|at|here)|not the (right|correct|best) (person|contact)|"
    r"wrong (person|contact|e-?mail)|(doesn't|does not|don't|do not) (work|handle) (here|that|this|marketing)|"
    r"(i('ve| have)|we('ve| have)) forwarded|forwarded (this|your (e-?mail|message|note))|"
    r"passed (this|your (e-?mail|message)) (along|on)|i('m| am) not (the (one|person)|in charge)|not in charge|"
    r"(has |have )?retired|left the (company|community|building))\b", I)
_WEAK_REFERRAL = re.compile(
    r"\b(please (contact|reach out to|call|e-?mail|speak (with|to)|talk to)|you (will|would|'ll) need to "
    r"(contact|speak|talk|reach)|best (person|contact) (is|would be|to)|handles? (all )?(our )?(marketing|admissions)|"
    r"in charge of (marketing|admissions)|(contact|call|e-?mail) (our|the) (administrator|director|owner|marketing|"
    r"admissions|corporate|office manager))\b", I)
_PLAN_REQ = re.compile(
    r"\b(send (me |us |over )?(the |your |that |a )?(one[- ]page )?plan|see (the |your )?plan|(the |your )?plan,? please|"
    r"like to see (it|the plan|your plan)|(would|'d) (like|love) (for you )?to (see|have|get|receive|send) "
    r"(it|me|us|the plan|your plan|that)|send it( over| to me| to us)?\b|yes,? please( send)?)\b", I)
_YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|please do|please send|interested|absolutely|of course|"
                  r"go ahead|why not|sounds good)\b", I)
_FULL = re.compile(
    r"\b(we('re| are) (currently )?(full|at capacity|fully (occupied|booked))|(full|at capacity) (right now|at (this|the) "
    r"(time|moment)|currently)|fully occupied|100\s?% (occupied|full)|no (current )?(availability|vacanc\w*|openings?|"
    r"open(ings)? (rooms?|beds?)|rooms? (available|open)|beds? (available|open))|(don't|do not|doesn't|does not) have "
    r"(any )?(open )?(rooms?|beds?|availability|openings?|vacanc\w*)|currently full|are full|is full|"
    r"zero (rooms|beds|openings)|none (available|open))\b", I)
_NOT_INTERESTED = re.compile(
    r"\b(not interested|no,? thank(s| you)|we('re| are) (good|all set|set)|all set|not (looking|in need)|"
    r"(don't|do not) need|no need|not at this time|we (do|handle) (our own|it in[- ]house)|"
    r"we (already )?have (a |an )?(company|agency|someone|marketing)|pass on this|we('ll| will) pass)\b", I)
_WHAT = re.compile(
    r"(\bwhat is this( about| regarding| for)?\b|\bwhat's this( about)?\b|\bwhat (is|was) this (e-?mail|message) "
    r"(about|regarding|for)\b|\bmay i (ask|know) what\b|\bwho is this\b(?! for)|\bwho are you\b|\bwhat company\b|"
    r"\bwhich company\b|\byour (company|business|organization)\b|\bwhat (do|does) (you|your company|surven) do\b|"
    r"\bwhat are you (selling|offering)\b|\bhow did you get\b|\bis this (spam|legit|a scam|real)\b|"
    r"\bwhat (kind|type) of (service|company|business)\b|\bare you (a|with a) (placement|referral|marketing|vendor)\b|"
    r"\bdo (we|i) (have|know) (a|an|you)\b|\bhave we (met|worked)\b|\bcontract with (you|your)\b)", I)
_FAMILY_Q = re.compile(
    r"\b(are you (looking|searching) (for|to)|for (yourself|your (mom|mother|dad|father|parent|loved one|wife|husband|"
    r"family))|loved one|who is (this|the room|it) for|what level of care|(memory care|assisted living) or (assisted "
    r"living|memory care|independent)|private pay|long[- ]term care insurance|medicaid|waiver|(schedule|book|set up|"
    r"come (in )?for) a tour|come (by|in|and see)|tour (the|our) (home|community|facility)|move[- ]?in date|when (are|is) "
    r"(you|he|she|they) (looking|wanting|planning) to move|what is your budget|(daily|monthly) rate|per month|"
    r"price (is|depends|dependent)|rates? (start|are|is)|give us a call|(would|do) you like to (schedule|tour|visit))\b", I)
_VACANCY = re.compile(
    r"\b(rooms? (available|open|opening)|beds? (available|open|opening)|open (rooms?|beds?|units?)|"
    r"(have|has|got) (a |one |two |three |four |five |\d+ |a few |some |several )?(rooms?|beds?|openings?|vacanc\w*|"
    r"units?|spots?)|availability|vacanc(y|ies)|openings?|as many as you (want|need)|a few (open|available)|"
    r"units? (available|open)|we do have|private (room|or shared)|shared rooms?|semi[- ]private)\b", I)
_INTEREST = re.compile(
    r"\b(call me|give me a call|(let's|lets) (talk|chat|connect|set up)|set up a (call|time|meeting)|"
    r"schedule a (call|meeting|time)|happy to (talk|chat|connect)|my (cell|number|phone) is|you can reach me|"
    r"reach me at|what time|(are you|i'm|i am) (free|available)|tell me more|i('m| am) interested|we('re| are) interested|"
    r"sounds (interesting|good)|(would|'d) (like|love) to (learn|hear|know) more|more (information|info|details)|"
    r"how does (it|this) work|how much (does|is|would)|what (does it|would it) cost|interested in (learning|hearing))\b", I)


def reply_meaning(body, quoted, subject, sender, rules):
    """(sub-class, confidence, reasons, extras) for one cold reply. body = their words without the signature."""
    camp = rules.get("campaign") or {}
    auto = rules.get("auto_reply") or {}
    q = (quoted or "").lower()
    offer = ("plan" if any(m in q for m in camp.get("plan_offer_markers") or []) else
             "tool_trial" if any(m in q for m in camp.get("tool_offer_markers") or []) else
             "rooms" if q.strip() else "unknown")
    extras = {"offer": offer, "rooms": tu.room_count(body), "kind": ""}
    text = (body or "").strip()
    local = (sender or "").split("@")[0].lower()
    subj = (subject or "").strip()

    if re.search(auto.get("subject") or r"$^", subj, I):
        return "auto_reply", "high", ["auto-reply subject"], extras
    if not text:
        extras["kind"] = "empty"
        return "auto_reply", "high", ["empty reply: nothing written above the quote"], extras
    if re.search(auto.get("sender_local") or r"$^", local, I):
        return "auto_reply", "high", ["automated sender"], extras
    if re.search(auto.get("body") or r"$^", text, I) and len(text) < 700:
        return "auto_reply", "high", ["auto-reply wording"], extras
    if tu.is_opt_out(text):
        return "opt_out", "high", ["opt-out wording"], extras
    if _STRONG_REFERRAL.search(text):
        return "wrong_person_or_referral", "high", ["says they are not the person / person left"], extras
    if _PLAN_REQ.search(text) or (offer in ("plan", "tool_trial") and _YES.search(text)):
        extras["kind"] = offer if offer in ("plan", "tool_trial") else "plan"
        return "asked_for_plan", "high" if offer in ("plan", "tool_trial") or "plan" in text.lower() else "medium", \
            ["said yes to the " + ("free tool" if offer == "tool_trial" else "one-page plan")], extras
    no_full = _FULL.sub(" ", text)
    vacancy = bool(_VACANCY.search(no_full)) or (extras["rooms"] or 0) > 0
    if _FULL.search(text) and not vacancy or extras["rooms"] == 0:
        extras["kind"] = "full"
        return "not_interested_or_full", "high", ["no open rooms"], extras
    if _NOT_INTERESTED.search(text) and not vacancy:
        extras["kind"] = "not_interested"
        return "not_interested_or_full", "high", ["not interested"], extras
    if _WHAT.search(text):
        return "question_what_is_this", "high", ["asks who Surven is"], extras
    family = bool(_FAMILY_Q.search(text))
    if _INTEREST.search(text) and not (family or vacancy):
        return "interested_call", "high", ["asks to talk or for details"], extras
    if vacancy or family or (_YES.search(text) and offer in ("rooms", "unknown")):
        why = ["answered like a family asked for a room"] if family else ["answered with open rooms"]
        conf = "high" if (vacancy or family) else "medium"
        return "vacancy_or_family_misread", conf, why, extras
    if _WEAK_REFERRAL.search(text):
        return "wrong_person_or_referral", "medium", ["points to someone else"], extras
    if _INTEREST.search(text):
        return "interested_call", "medium", ["asks to talk"], extras
    return "question_what_is_this", "low", ["unclear reply: read it"], extras


# ---------------------------------------------------------------- normalizing the connector JSON

def _addr(v):
    if isinstance(v, dict):
        v = v.get("email") or v.get("address") or ""
    v = str(v or "").strip()
    m = re.search(r"<([^>]+)>", v)
    return (m.group(1) if m else v).strip().lower()


def domain_of(addr):
    return addr.split("@")[-1].lower() if "@" in (addr or "") else ""


def in_domains(addr, domains):
    d = domain_of(addr)
    return any(d == x or d.endswith("." + x) for x in (domains or []) if x)


def _has_body(m):
    return bool(m.get("plaintextBody") or m.get("htmlBody") or m.get("plaintext_body") or m.get("html_body"))


def norm_message(m, thread_id=None):
    labels = m.get("labelIds") or m.get("label_ids") or []
    return {
        "id": m.get("id") or "",
        "thread_id": m.get("threadId") or m.get("thread_id") or thread_id or "",
        "sender": _addr(m.get("sender") or m.get("from")),
        "to": [_addr(x) for x in (m.get("toRecipients") or m.get("to_recipients") or m.get("to") or [])],
        "cc": [_addr(x) for x in (m.get("ccRecipients") or m.get("cc_recipients") or m.get("cc") or [])],
        "subject": m.get("subject") or "",
        "date": m.get("date") or "",
        "labels": list(labels),
        "snippet": m.get("snippet") or "",
        "body": tu.body_of(m) if _has_body(m) else "",
        "has_body": _has_body(m),
        "view_url": m.get("viewUrl") or m.get("view_url") or "",
        "attachments": [a.get("filename") for a in (m.get("attachments") or []) if isinstance(a, dict)],
    }


def threads_in(obj):
    """Every thread dict inside one connector result (get_thread, search_threads, or a list)."""
    if isinstance(obj, list):
        out = []
        for x in obj:
            out += threads_in(x)
        return out
    if not isinstance(obj, dict):
        return []
    if "threads" in obj:
        return threads_in(obj.get("threads") or [])
    if "messages" in obj or "id" in obj:
        return [obj]
    return []


def norm_thread(t):
    msgs = [norm_message(m, t.get("id")) for m in (t.get("messages") or [])]
    msgs.sort(key=lambda m: m["date"] or "")
    count = t.get("messageCount") or t.get("message_count") or len(msgs)
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = len(msgs)
    return {"id": t.get("id") or (msgs[0]["thread_id"] if msgs else ""), "count": count,
            "view_url": t.get("viewUrl") or t.get("view_url") or "", "messages": msgs}


# ---------------------------------------------------------------- who wrote it

def is_own(addr, rules):
    a = (addr or "").lower()
    return a in (rules.get("own_addresses") or []) or in_domains(a, rules.get("own_domains") or [])


def _group_match(addr, groups):
    for key, ent in (groups or {}).items():
        if addr in [s.lower() for s in ent.get("senders") or []] or in_domains(addr, ent.get("domains")) \
                or in_domains(addr, ent.get("relay_domains")):
            return key, ent
    return None, None


def is_bulk(addr, rules):
    nz = rules.get("noise") or {}
    local = addr.split("@")[0]
    labels = domain_of(addr).split(".")
    sub = labels[0] if len(labels) > 2 else ""
    return bool(re.search(nz.get("bulk_local") or r"$^", local, I)) or in_domains(addr, nz.get("bulk_domains")) \
        or sub in (nz.get("bulk_subdomains") or [])


def strip_re(subject):
    return re.sub(r"^(?:\s*(?:re|fw|fwd|aw)\s*:\s*|\s*\[external\]\s*)+", "", subject or "", flags=I).strip()


def cold_target(msg, rules):
    """The joey@<cold domain> address this message went to, if it looks like a campaign reply."""
    camp = rules.get("campaign") or {}
    tos = msg["to"] + msg["cc"]
    cold = [a for a in tos if in_domains(a, rules.get("cold_domains"))]
    if not cold or is_own(msg["sender"], rules):
        return ""
    mailbox = [a for a in cold if a.split("@")[0] in (camp.get("mailbox_local_parts") or ["joey"])]
    subj = strip_re(msg["subject"]).lower()
    campaign_subj = any(s in subj for s in camp.get("subjects") or [])
    text = (msg["body"] or msg["snippet"] or "").lower()
    quote = any(m in text for m in camp.get("quote_markers") or [])
    cold_only = [a for a in mailbox if in_domains(a, rules.get("cold_only_domains"))]
    if campaign_subj or quote:
        return (mailbox or cold)[0]
    if cold_only and not is_bulk(msg["sender"], rules):
        return cold_only[0]
    return ""


def header_class(msg, rules):
    """(class, sub, reason, extra) from sender, recipients, subject, snippet and labels only."""
    s, subj = msg["sender"], msg["subject"] or ""
    gv = rules.get("google_voice") or {}
    nz = rules.get("noise") or {}
    if s in (rules.get("ignore") or []) or in_domains(s, [d for d in rules.get("ignore") or [] if "@" not in d]):
        return "noise", "ignored", "on the ignore list", {}
    if is_own(s, rules):
        if re.search((rules.get("automation") or {}).get("self_subjects") or r"$^", strip_re(subj), I) or \
                any(is_own(a, rules) for a in msg["to"]):
            return "automation_alert", "self", "Joey's own automation email", {}
        return "noise", "sent", "sent by Joey", {}
    if in_domains(s, gv.get("sender_domains")) or s in (gv.get("senders") or []):
        low = re.sub(r"\s+", "", subj.lower())
        own_line = any(re.sub(r"\s+", "", w.lower()) in low for w in gv.get("own_line_words") or [])
        return "google_voice_text", "own_line" if own_line else "person", \
            "text from your own business line" if own_line else "Google Voice forward", {}
    target = cold_target(msg, rules)
    if target:
        return "cold_reply", "", "reply to the cold email (" + domain_of(target) + ")", {"cold_to": target}
    key, ent = _group_match(s, rules.get("clients"))
    if key:
        relay = in_domains(s, ent.get("relay_domains"))
        auto = re.search(rules.get("client_automation_subjects") or r"$^", strip_re(subj), I) and \
            not re.match(r"^\s*(re|fw|fwd)\s*:", subj, I)
        return "client", "automation_copy" if auto else "message", ent.get("label") or key, \
            {"group": key, "label": ent.get("label") or key, "relay": relay}
    if s in [x.lower() for x in rules.get("coach_recap_senders") or []]:
        m = re.search(rules.get("coach_recap_subject") or r"$^", subj, I)
        if m:
            who = re.sub(r"[^a-z]", "", m.group("who").lower())
            for ck, ce in (rules.get("coaches") or {}).items():
                keys = [re.sub(r"[^a-z]", "", (ce.get("label") or "").lower())] + \
                       [re.sub(r"[^a-z]", "", d.split(".")[0]) for d in ce.get("domains") or []] + \
                       [re.sub(r"[^a-z]", "", x.split("@")[0]) for x in ce.get("senders") or []]
                if any(k and len(k) > 3 and (k in who or who in k) for k in keys):
                    return "coach", "call_recap", ce.get("label") or ck, {"group": ck, "label": ce.get("label") or ck}
    if re.search(nz.get("subjects") or r"$^", strip_re(subj), I):
        return "noise", "bulk", "calendar, receipt or notice", {}
    key, ent = _group_match(s, rules.get("coaches"))
    if key:
        return "coach", "email", ent.get("label") or key, {"group": key, "label": ent.get("label") or key}
    key, ent = _group_match(s, rules.get("vendors"))
    if key:
        person = not is_bulk(s, rules) and not s.split("@")[0].startswith("team")
        return "vendor_or_data_sale", "person" if person else "system", ent.get("label") or key, \
            {"group": key, "label": ent.get("label") or key}
    au = rules.get("automation") or {}
    if in_domains(s, au.get("sender_domains")) or re.search(au.get("subjects") or r"$^", strip_re(subj), I):
        return "automation_alert", "lead_alert", "lead or booking alert", {}
    labels = set(msg["labels"])
    if labels & set(nz.get("bulk_categories") or []) or is_bulk(s, rules) or "CATEGORY_UPDATES" in labels:
        return "noise", "bulk", "bulk or automated mail", {}
    return "noise", "unknown_person", "someone new in Primary", {}


# ---------------------------------------------------------------- one full thread -> one work item

def _iso_et(date):
    d = et.parse(date)
    return et.to_et(d).strftime("%Y-%m-%d %H:%M") if d else ""


def latest_inbound(thread, rules):
    inbound = [m for m in thread["messages"] if not is_own(m["sender"], rules)]
    return inbound[-1] if inbound else (thread["messages"][-1] if thread["messages"] else None)


def answered(thread, msg, rules):
    """True when a message from Joey's own addresses comes after the message we would answer."""
    after = [m for m in thread["messages"] if (m["date"] or "") > (msg["date"] or "")]
    return any(is_own(m["sender"], rules) for m in after)


def classify_thread(raw, rules):
    """A work item for one thread (raw connector JSON or an already normalized thread)."""
    t = raw if "count" in raw and raw.get("messages") and "has_body" in raw["messages"][0] else norm_thread(raw)
    msg = latest_inbound(t, rules)
    if not msg:
        return {"thread_id": t["id"], "class": "noise", "sub": "empty", "action": "label_only", "reasons": ["no messages"]}
    cls, sub, reason, extra = header_class(msg, rules)
    item = {
        "thread_id": t["id"], "message_id": msg["id"], "class": cls, "sub": sub, "confidence": "high",
        "reasons": [reason], "from": msg["sender"], "from_domain": domain_of(msg["sender"]),
        "subject": msg["subject"], "reply_subject": msg["subject"] if re.match(r"^\s*re\s*:", msg["subject"], I)
        else "Re: " + strip_re(msg["subject"]) if msg["subject"] else "Re:",
        "date": _iso_et(msg["date"]), "view_url": msg["view_url"] or t.get("view_url") or "",
        "messages_in_thread": t["count"], "answered": answered(t, msg, rules), "has_body": msg["has_body"],
        "label": extra.get("label", ""), "group": extra.get("group", ""),
        "reply_to": "", "reply_mode": "", "copy_context": "", "require_link": False,
        "action": "label_only", "needs_joey": False, "template": "",
    }
    body_all = msg["body"]
    if cls == "google_voice_text":
        body_all = tu.strip_footer(body_all, (rules.get("google_voice") or {}).get("footer_cut"))
    new, quoted = tu.split_reply(body_all)
    body, sig = tu.split_signature(new)
    sig = tu.trim_legal(sig)
    item["text"] = tu.shorten_links(body)[:700]
    item["signature"] = tu.shorten_links(sig)[:300]
    if not msg["has_body"]:
        item["text"] = tu.shorten_links(msg["snippet"])[:300]

    if cls == "cold_reply":
        item["cold_to"] = extra.get("cold_to", "")
        greet = tu.quoted_greeting(quoted)
        item["first"], item["first_source"] = tu.first_name_guess(body, sig, greet, msg["sender"])
        pats = (rules.get("campaign") or {}).get("home_patterns")
        item["home"], item["home_source"] = tu.home_guess(quoted, sig + "\n" + tu.quoted_signature(quoted), pats)
        if not item["home"]:
            guess = tu.domain_home_guess(msg["sender"])
            if guess:
                item["home"], item["home_source"] = guess, "email domain (a guess: check it)"
        if not item["first"]:
            item["first"], item["first_source"] = tu.first_name_guess(body, tu.quoted_signature(quoted))
        if msg["has_body"]:
            sub, conf, why, ex = reply_meaning(body, quoted, msg["subject"], msg["sender"], rules)
        else:  # search preview only: an auto-reply shows in the subject or sender; anything else needs a read
            auto = rules.get("auto_reply") or {}
            is_auto = re.search(auto.get("subject") or r"$^", msg["subject"] or "", I) or \
                re.search(auto.get("sender_local") or r"$^", msg["sender"].split("@")[0], I)
            sub, conf, why = ("auto_reply", "high", ["auto-reply subject or sender"]) if is_auto else \
                ("not_read", "low", ["not read yet: get the full thread"])
            ex = {"offer": "unknown", "rooms": None, "kind": ""}
        item.update({"sub": sub, "confidence": conf, "offer": ex["offer"], "rooms": ex["rooms"], "kind": ex["kind"]})
        item["reasons"] += why
        item["template"] = sub
        if sub == "not_read":
            item["action"] = "read"
        elif sub in ("auto_reply",):
            item["action"] = "label_only"
        elif sub == "opt_out":
            item["action"] = "flag"
        elif sub == "not_interested_or_full" and ex["kind"] == "not_interested":
            item["action"] = "label_only"
        else:
            item["action"] = "draft_plan" if sub == "asked_for_plan" else "draft_reply"
            item.update({"reply_to": msg["sender"], "reply_mode": "email", "copy_context": "prospect_email",
                         "require_link": sub in ("vacancy_or_family_misread", "asked_for_plan",
                                                 "question_what_is_this", "interested_call"), "needs_joey": True})
            if sub == "not_interested_or_full":
                item["template"] = "full"
            if sub == "asked_for_plan" and ex["kind"] == "tool_trial":
                item["template"] = "asked_for_plan_tool"
    elif cls == "google_voice_text":
        if sub == "person":
            item.update({"action": "draft_reply", "reply_to": msg["sender"], "reply_mode": "gv_sms",
                         "copy_context": "prospect_sms", "needs_joey": True, "template": "google_voice"})
        else:
            item["action"] = "label_only"
    elif cls == "client":
        if sub == "automation_copy":
            item["action"] = "label_only"
        else:
            relay = extra.get("relay")
            item.update({"action": "draft_reply", "copy_context": "client", "needs_joey": True, "template": "client",
                         "reply_mode": "copy_to_ghl" if relay else "email", "reply_to": "" if relay else msg["sender"]})
    elif cls == "coach":
        item["action"] = "learning"
        item["learning"] = {"Title": strip_re(msg["subject"])[:120] or "Coach email", "Source": item["label"],
                            "date:Date:start": item["date"][:10], "date:Date:is_datetime": 0,
                            "Link": item["view_url"], "Applied": "__NO__"}
    elif cls == "vendor_or_data_sale":
        if sub == "person":
            item.update({"action": "draft_reply", "reply_to": msg["sender"], "reply_mode": "email",
                         "copy_context": "client", "needs_joey": True, "template": "vendor"})
        else:
            act = re.search(rules.get("vendor_action_subject") or r"$^", msg["subject"], I)
            item.update({"action": "summarize" if act else "label_only", "needs_joey": bool(act)})
    elif cls == "noise" and sub == "unknown_person":
        item.update({"action": "summarize", "needs_joey": True})
    if item["answered"] and item["action"] in ("draft_reply", "draft_plan"):
        item.update({"action": "label_only", "needs_joey": False})
        item["reasons"].append("Joey already answered in this thread")
    return item


# ---------------------------------------------------------------- CLI

def load_threads(paths):
    out = []
    for p in paths:
        files = [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".json")] if os.path.isdir(p) else [p]
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    out += threads_in(json.load(fh))
            except (OSError, ValueError) as e:
                print(f"skip {os.path.basename(f)}: {type(e).__name__}", file=sys.stderr)
    seen, uniq = set(), []
    for t in out:
        tid = t.get("id")
        if tid and tid not in seen:
            seen.add(tid)
            uniq.append(t)
    return uniq


def counts(items):
    c = collections.Counter()
    for it in items:
        c[it["class"] + ("/" + it["sub"] if it.get("sub") else "")] += 1
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classify Gmail threads for the Inbox Desk.")
    ap.add_argument("paths", nargs="+", help="connector JSON files or folders of them")
    ap.add_argument("--private", default=st.PRIVATE)
    ap.add_argument("--json", action="store_true", help="print the full work items (has message text)")
    ap.add_argument("--out", help="also write the work items to this file")
    a = ap.parse_args(argv)
    rules = st.load_rules(private=a.private)
    items = [classify_thread(t, rules) for t in load_threads(a.paths)]
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)
    if a.json:
        print(json.dumps(items, indent=1))
    else:
        for it in items:
            print(f"{it['thread_id']}  {it['class']}{'/' + it['sub'] if it.get('sub') else ''}  "
                  f"{it.get('confidence', '')}  {it['action']}  {it.get('from_domain', '')}")
    c = counts(items)
    print("counts: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) if c else "counts: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
