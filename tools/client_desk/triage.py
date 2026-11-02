"""Unknown-caller triage: robocall or family?

The care-home planners park every inbound caller with no name ("Caller 1234") until Joey answers "robocall" or
"family". This module reads the same evidence Joey would and gives each caller a verdict with the reason, so he can
answer every NEED YOU question in one pass:

  robocall-likely   nobody spoke when the call was answered, a burst of new numbers in one hour and area code, a
                    number almost the same as another unknown caller's, a recorded or automated message
  family-likely     the caller talked about a loved one, a room, a tour or a price, a hospital or social worker
                    (a referral), or texted back, or picked up our call back and talked
  not-a-family      asked about a job, or a sales or listing call
  unclear           not enough to tell: the page says which way it leans and to listen to the recording

Only the last 4 digits of a number are ever shown. Pure functions over the raw pull.
"""
import datetime as dt
import re

from tools.client_desk import metrics as M

TRIAGE_DAYS = 14
WAVE_MINUTES = 60
WAVE_SIZE = 3
SILENT_WORDS = 2

GREETING = re.compile(r"^(hey|hi|hello|hiya|yes|yeah|yep|ok|okay|good (morning|afternoon|evening)|hey there|hi there|"
                      r"hello hello|hello hello hello|anyone there|is anyone there|can you hear me|how are you|"
                      r"i'm good|im good|good|fine|thank you|thanks|bye|goodbye|how can i help you|"
                      r"how may i help you|what can i do for you|who is this)$")
FAMILY = re.compile(r"\b(mom|mother|dad|father|grand(?:ma|mother|pa|father)|husband|wife|aunt|uncle|sister|brother|"
                    r"loved one|my (?:son|daughter|parent|parents)|assisted living|rooms?|beds?|place for|move in|"
                    r"moving in|tour|visit|how much|price|cost|rates?|medicaid|medicare|dementia|alzheimer\w*|"
                    r"memory care|care for (?:my|her|him)|looking for (?:a )?(?:place|home|room))\b", re.I)
REFERRAL = re.compile(r"\b(social worker|case manager|discharg\w*|hospital|rehab|nursing home|hospice|referr\w*|"
                      r"placement agent|admissions|patient)\b", re.I)
JOB = re.compile(r"\b(hiring|hire|jobs?|positions?|apply|application|applying|resume|interview|employment|"
                 r"caregiver position|activity aid\w*|aide position|cna|work for you|looking for work)\b", re.I)
ROBO = re.compile(r"\b(press (?:one|1|two|2|nine|9|star)|this is a recorded|recorded message|automated (?:call|message)|"
                  r"final notice|your account|credit card|warranty|do not hang up|this call is from)\b", re.I)
VENDOR = re.compile(r"\b(google (?:listing|business|my business|maps)|business listing|verify (?:your|the) "
                    r"(?:business|listing)|listing verification|search engine|seo|marketing|advertis\w*|yelp|"
                    r"merchant services|funding|loan|web ?site design|web design|survey)\b", re.I)


def own_sentence(s, voice_names, home_words):
    """True for words from the home's side or plain greetings: 'This is Joey from ...', 'Hello?'."""
    t = re.sub(r"[^a-z' ]+", " ", s.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if not t or GREETING.match(t):
        return True
    for n in voice_names:
        if t.startswith("this is " + n) or (n + " from") in t or t == n:
            return True
    if home_words and sum(1 for w in home_words if w in t.split()) >= 2 and len(t.split()) <= 8:
        return True
    return False


def caller_words(summary, voice_names, home_words):
    """(word count, text) of what was said that is not a greeting or the home's own hello."""
    if not summary or summary.get("status") != "ok":
        return None, ""
    keep = []
    for seg in (summary.get("text") or "").split(" | "):
        _, _, body = seg.partition(": ")
        body = body or seg
        for sent in re.split(r"(?<=[.?!])\s+", body):
            if sent.strip() and not own_sentence(sent, voice_names, home_words):
                keep.append(sent.strip())
    text = " ".join(keep)
    return len(re.findall(r"[A-Za-z']+", text)), text


def _phone(c):
    return (c or {}).get("phone") or {}


def triage(raw, cls, p, now, days=TRIAGE_DAYS):
    contacts = {c["id"]: c for c in raw.get("contacts") or []}
    msgs = M.by_contact(raw)
    voice = [n.lower() for n in p.get("operator_voice_names") or []]
    home_words = [w for w in re.findall(r"[a-z]+", (raw.get("location", {}).get("name") or p.get("label") or "").lower())
                  if len(w) > 2]
    loc = raw.get("location_id") or p.get("location") or ""
    home6 = (raw.get("internal") or {}).get("home_block6") or ""
    recent = now - dt.timedelta(days=days)

    # first inbound call of every unnamed outside contact, for waves and near-identical numbers
    firsts = []
    for cid, mm in msgs.items():
        c = contacts.get(cid)
        kind = (cls.get(cid) or {}).get("kind")
        # unnamed callers, plus named ones whose name is only a caller ID (classified unknown_caller)
        if not c or (c.get("named") and kind != "unknown_caller") or kind in ("internal", "partner"):
            continue
        calls = [m for m in mm if M.is_call(m) and m.get("dir") == "inbound" and M.ts(m.get("when"))]
        if calls:
            firsts.append((cid, M.ts(calls[0]["when"]), _phone(c)))

    items = []
    for cid in M.ids_of(cls, "unknown_caller"):
        c = contacts.get(cid) or {}
        mm = msgs.get(cid, [])
        calls = [m for m in mm if M.is_call(m) and m.get("dir") == "inbound" and M.ts(m.get("when"))]
        texts = [m for m in mm if m.get("dir") == "inbound" and m.get("type") in M.TEXT_TYPES | M.EMAIL_TYPES
                 and M.ts(m.get("when"))]
        if not calls and not texts:
            continue
        last = max([M.ts(m["when"]) for m in calls + texts])
        first = min([M.ts(m["when"]) for m in calls + texts])
        ph = _phone(c)

        robo, human, why = 0, 0, []
        call_rows, heard_all, answered, silent_answered = [], [], 0, 0
        vm_empty = vm_unread = missed_only = 0
        for m in calls:
            summ = (raw.get("transcripts") or {}).get(m["id"])
            n, heard = caller_words(summ, voice, home_words)
            st = m.get("cst") or m.get("status") or ""
            dur = m.get("dur") if isinstance(m.get("dur"), (int, float)) else None
            if st == "completed":
                answered += 1
                if n is not None and n <= SILENT_WORDS:
                    silent_answered += 1
            elif st == "voicemail" and n is not None and n <= SILENT_WORDS:
                vm_empty += 1
            elif st == "voicemail" and n is None:
                vm_unread += 1
            elif st in ("no-answer", "noanswer", "busy", "missed") and not m.get("rec"):
                missed_only += 1
            if heard:
                heard_all.append(heard)
            call_rows.append({"when": m["when"], "dur": dur, "status": st, "words": n, "heard": heard[:140],
                              "transcript": (summ or {}).get("status", "none") if (m.get("rec") or dur) else "none"})
        said = " ".join(heard_all) + " " + " ".join(m.get("text") or "" for m in texts)
        call_days = {M.et.to_et(M.ts(m["when"])).date() for m in calls}
        talked = [r for r in call_rows if r["status"] == "completed" and (r["words"] or 0) >= 15]
        called_back_talk = any(M.talk(m) for m in mm if m.get("dir") == "outbound")
        real_texts = [m for m in texts if (m.get("text") or "").strip() and not M.NO_ANSWER_NEEDED.match(m.get("text") or "")]

        # neighbours in time and number
        wave = 0
        near = []
        if calls and ph.get("area"):
            t0 = M.ts(calls[0]["when"])
            wave = 1 + sum(1 for oc, ot, oph in firsts if oc != cid and oph.get("area") == ph["area"]
                           and abs((ot - t0).total_seconds()) <= WAVE_MINUTES * 60)
            near = [oph.get("last4") for oc, ot, oph in firsts if oc != cid and ph.get("block8")
                    and oph.get("block8") == ph["block8"] and abs((ot - t0).total_seconds()) <= 14 * 86400]
        verdict = None
        m_job, m_robo, m_vendor = JOB.search(said), ROBO.search(said), VENDOR.search(said)
        m_fam, m_ref = FAMILY.search(said), REFERRAL.search(said)
        if m_job:
            verdict, why = "not-a-family", ['asked about work ("%s")' % m_job.group(0).lower()]
        elif m_robo:
            verdict, why = "robocall-likely", ['recorded or automated message ("%s")' % m_robo.group(0).lower()]
        elif m_vendor and not (m_fam or m_ref):
            verdict, why = "not-a-family", ['sales or listing call ("%s")' % m_vendor.group(0).lower()]
        elif m_ref:
            verdict, why = "family-likely", ['sounds like a referral source ("%s"): call back today' % m_ref.group(0).lower()]
        elif m_fam:
            verdict, why = "family-likely", ['talked about "%s"' % m_fam.group(0).lower()]

        if answered and silent_answered == answered:
            robo += 2
            why.append("answered %s, nobody spoke" % ("once" if answered == 1 else "%d times" % answered))
        if wave >= WAVE_SIZE:
            robo += 2
            why.append("%d new numbers from area code %s called within an hour (robocall wave)" % (wave, ph["area"]))
        if near:
            robo += 2
            why.append("number almost the same as %s" % ", ".join("Caller " + x for x in sorted(set(near)) if x))
        if home6 and ph.get("block6") == home6:
            robo += 1
            why.append("number starts like the home's own number (a common robocall trick)")
        if vm_empty:
            robo += 1
            why.append("left %s with no words" % ("a voicemail" if vm_empty == 1 else "%d voicemails" % vm_empty))
        if vm_unread:
            robo += 1
            why.append("left %s with no transcript (often an empty recording)" % (
                "a voicemail" if vm_unread == 1 else "%d voicemails" % vm_unread))
        if missed_only and not answered and not (vm_empty or vm_unread):
            robo += 1
            why.append("hung up before anyone answered, no voicemail")
        if real_texts:
            human += 3
            why.append("texted us")
        if talked:
            human += 2
            why.append("talked for %s" % _secs(max(r["dur"] or 0 for r in talked)))
        if called_back_talk:
            human += 2
            why.append("picked up when we called back")
        if len(call_days) >= 2 and silent_answered < answered:
            human += 1
            why.append("called on %d different days" % len(call_days))
        elif len(calls) >= 2 and len(call_days) == 1 and not silent_answered:
            why.append("called %d times the same day" % len(calls))
        if not call_rows and not real_texts:
            why.append("no call details")
        if verdict is None:
            if robo >= 2 and robo > human:
                verdict = "robocall-likely"
            elif human >= 3 and human > robo:
                verdict = "family-likely"
            else:
                verdict = "unclear"
        lean = ""
        if verdict == "unclear":
            lean = "robocall" if robo > human else ("family" if human > robo else "")
            no_words = [r for r in call_rows if r["transcript"] != "ok" and (r["dur"] or 0) > 0]
            if no_words:
                why.append("listen to the recording to be sure")
        answer = {"robocall-likely": "robocall", "family-likely": "family", "not-a-family": "not a family",
                  "unclear": "not sure yet"}[verdict]
        label = M.caller_label(c)
        items.append({
            "cid": cid, "label": label, "last4": ph.get("last4", ""), "area": ph.get("area", ""),
            "verdict": verdict, "lean": lean, "reason": "; ".join(why) or "no signals",
            "robo": robo, "human": human, "older": last < recent,
            "first": first.isoformat(), "last": last.isoformat(), "added": c.get("added"), "calls": call_rows,
            "texts": [{"when": m["when"], "text": (m.get("text") or "")[:140]} for m in texts][-3:],
            "answer": "%s: %s" % (label, answer),
            "link": "https://app.gohighlevel.com/v2/location/%s/contacts/detail/%s" % (loc, cid),
            "stage": M.stage_of(c),
        })
    order = {"family-likely": 0, "unclear": 1, "not-a-family": 2, "robocall-likely": 3}
    items.sort(key=lambda x: (x["older"], order[x["verdict"]], -M.ts(x["last"]).timestamp()))
    return items


def _secs(s):
    s = int(s or 0)
    return "%d:%02d" % (s // 60, s % 60)


def answers_text(items):
    """One block Joey can paste or read off when he answers the planner."""
    return "\n".join(i["answer"] + (" (%s)" % i["reason"] if i["verdict"] != "robocall-likely" else "") for i in items)


def counts(items):
    out = {"robocall-likely": 0, "family-likely": 0, "not-a-family": 0, "unclear": 0}
    for i in items:
        out[i["verdict"]] += 1
    return out
