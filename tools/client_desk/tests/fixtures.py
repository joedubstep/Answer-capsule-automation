"""Synthetic GoHighLevel data for the Client Desk tests. Every person, place, phone and email here is made up
(555 numbers, example.com addresses, names like "Pat Example").

The shapes copy what the live API returned in a read-only check of the AGC location on 2026-11-02 (contacts search,
opportunities search, the message export, call transcriptions), and the ids are AGC's non-secret system ids from
config/surven.json so profile.load("agc") works unchanged. write_fake_dir(path) writes one JSON file per GET path,
the way shared.ghl's GHL_FAKE_DIR hook reads them.
"""
import datetime as dt
import json
import os

NOW = dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.timezone.utc)        # Fri Nov 6, 7:00am ET
MONDAY = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)     # Mon Nov 2, 7:00am ET
LOC = "ySKGXQBLqevOlFCmV1Wo"
FAM = "XfVVFzt8CXRnTtc9PRq5"
PAR = "MVOEVgIdYEGt21HZH8R6"
TOUR = "uQEkJzpLsRP579RqHeXV"
ALERT = "C0oN6jnp768gCNqNIgZY"    # Joey's alert contact id in config/surven.json (a system id, not personal data)

FS = {  # family stages
    "engaged": "a92b312f-c8ee-48e5-8080-4350387ce461", "qual": "381b3d3e-db31-4421-ab69-43f3a6e346ee",
    "tour_booked": "c56cddbc-f036-427b-b0bc-351038253c27", "attended": "2f55ef23-fe94-4eca-900c-c2207466636a",
    "post_tour": "4cce855f-f476-4129-b0af-77ab13b85b57", "move_in": "940796bc-fa0b-4a3b-992a-fa7aeeeec091",
}
PS = {  # partner stages, in pipeline order
    "to_call": "bcfe2271-8cd3-4ccd-8322-3f82997de9aa", "no_answer": "fb0e2d5a-e1f7-4936-a07b-d664956b282d",
    "talked": "30b96d18-c305-4131-80d3-fbfa34f1fe43", "yes": "dd895e6d-7125-431e-b71f-b206d2e3cd99",
    "info_sent": "a08af2a1-2f23-4ca2-96ef-ed90ab2ea920", "referral": "f2dfdc79-8a1e-413c-ba8c-88f90018bc9c",
    "not_fit": "0627e68b-77a4-4a18-bd2b-fe93ff82f7ff",
}
F = {"agent_stage": "PPg3tiYdrvINsAH8WXlB", "call_outcome": "rUXPM8VL4FimV3xfrM6O", "tour_result": "OxNh9FqAZlNXhv8AJWVg",
     "partner_code": "gopqlOxXEKV5MIl9H07E", "referred_by": "NnRHXSUdnr7xSboZvdjz", "whisper": "neb21JJh6i27M52WJqla"}
FIELD_NAMES = {"agent_stage": "Agent Stage", "call_outcome": "SVN Call Outcome", "tour_result": "SVN Tour Result",
               "partner_code": "Partner Code", "referred_by": "Referred By Partner", "whisper": "Agent Whisper"}

USER_PHONE = "+15550109999"
HOME_PHONE = "+15552019000"   # the home's own line; caller numbers 555-201-00xx share its first 6 digits


def at(days=0, hours=0, minutes=0, base=None):
    return ((base or NOW) - dt.timedelta(days=days, hours=hours, minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ahead(days=0, hours=0):
    return (NOW + dt.timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def cf(**kv):
    return [{"id": F[k], "value": v} for k, v in kv.items()]


def contact(cid, first="", last="", phone=None, email=None, tags=(), added=None, fields=None, company="", source=""):
    return {"id": cid, "firstName": first, "lastName": last, "phone": phone, "email": email, "tags": list(tags),
            "dateAdded": added or at(days=30), "customFields": fields or [], "companyName": company, "source": source,
            "dnd": False, "type": "lead"}


def opp(oid, cid, pipe, stage, status="open", created=None, changed=None, name="", company=""):
    return {"id": oid, "contactId": cid, "pipelineId": pipe, "pipelineStageId": stage, "status": status,
            "createdAt": created or at(days=27), "lastStageChangeAt": changed or created or at(days=27),
            "lastStatusChangeAt": changed or created or at(days=27), "updatedAt": changed or at(days=27),
            "name": name, "contact": {"id": cid, "companyName": company}}


_n = [0]


def msg(cid, typ, direction, when, status=None, dur=None, cst=None, body=None, subject=None, source=None, rec=False,
        mid=None):
    _n[0] += 1
    m = {"id": mid or "m%04d" % _n[0], "contactId": cid, "conversationId": "cv_" + cid, "messageType": typ,
         "direction": direction, "dateAdded": when, "status": status, "source": source, "locationId": LOC,
         "userId": "u_joey" if direction == "outbound" else None, "attachments": []}
    if typ in ("TYPE_CALL", "TYPE_CAMPAIGN_CALL"):
        m["meta"] = {"call": {"status": cst or status, **({"duration": dur} if dur is not None else {})}}
        if rec:
            m["attachments"] = ["https://api.example.com/Recordings/RE" + m["id"]]
    if body is not None:
        m["body"] = body
    if subject is not None:
        m["subject"] = subject
    return m


def build():
    _n[0] = 0
    C, O, MS, EV, TX = [], [], [], [], {}

    # internal records
    C.append(contact(ALERT, "Joey", "Alert", phone="+15550100001", tags=["owner-joey"], added=at(days=60)))
    C.append(contact("staff1", "Sam", "Staffer", phone="+15550100002", tags=["svn-0-staff"], added=at(days=60)))
    C.append(contact("userph", "Owner", "Line", phone=USER_PHONE, added=at(days=50)))
    C.append(contact("test1", "Test", "Person", phone="+15550100003", added=at(days=5)))
    for i in range(30):   # the planner texting Joey: never counted as work for the home
        MS.append(msg(ALERT, "TYPE_SMS", "outbound", at(days=1, minutes=i), status="delivered", source="app",
                      body="Calls today: 2"))

    # families
    C.append(contact("fam1", "Pat", "Example", phone="+15553000001", email="pat@example.com", added=at(days=3),
                     source="Sample Grove website"))
    MS += [msg("fam1", "TYPE_CAMPAIGN_CALL", "outbound", at(days=3, minutes=-4), status="completed", dur=95,
               cst="completed", source="workflow"),
           msg("fam1", "TYPE_SMS", "inbound", at(days=2), status="delivered", body="Yes please call me after 3"),
           msg("fam1", "TYPE_SMS", "outbound", at(days=2, minutes=-10), status="delivered", source="app",
               body="Okay, I will call after 3.")]
    O.append(opp("o_f1", "fam1", FAM, FS["tour_booked"], changed=at(days=2)))
    EV.append({"id": "ev1", "contactId": "fam1", "calendarId": TOUR, "startTime": ahead(days=3), "endTime": ahead(days=3, hours=1),
               "dateAdded": at(days=2), "appointmentStatus": "confirmed", "deleted": False, "createdBy": {"source": "app"}})

    C.append(contact("fam2", "Lee", "Sample", phone="+15553000002", added=at(days=20),
                     fields=cf(agent_stage="thinking it over")))
    MS.append(msg("fam2", "TYPE_CALL", "inbound", at(days=20), status="completed", dur=300, cst="completed", rec=True))
    O.append(opp("o_f2", "fam2", FAM, FS["post_tour"], changed=at(days=2)))

    C.append(contact("fam3", "Dana", "Demo", phone="+15553000003", added=at(days=40),
                     fields=cf(tour_result="Showed - Moving In")))
    EV.append({"id": "ev2", "contactId": "fam3", "calendarId": TOUR, "startTime": at(days=5), "endTime": at(days=5, hours=-1),
               "dateAdded": at(days=9), "appointmentStatus": "showed", "deleted": False, "createdBy": {"source": "app"}})
    O.append(opp("o_f3", "fam3", FAM, FS["move_in"], status="won", changed=at(days=1)))

    C.append(contact("fam4", "Robin", "Placeholder", phone="+15553000004", added=at(days=2)))
    MS.append(msg("fam4", "TYPE_SMS", "inbound", at(hours=30), status="delivered", body="Do you have a room for my aunt?"))

    # a test tour on the alert contact: never counted
    EV.append({"id": "zdz3aYYPuq4AROP1zOAo", "contactId": ALERT, "calendarId": TOUR, "startTime": at(days=4),
               "endTime": at(days=4, hours=-1), "dateAdded": at(days=6), "appointmentStatus": "showed", "deleted": False})

    # referral partners
    def partner(cid, code, place, stage, ptype, status="open", email=None, tags=(), changed=None, whisper=""):
        fields = cf(partner_code=code, **({"whisper": whisper} if whisper else {}))
        C.append(contact(cid, "", "", phone="+1555400%04d" % code, email=email, company=place, added=at(days=27),
                         tags=["referral-partner", "partner-call-first", "partner-" + ptype] + list(tags), fields=fields))
        O.append(opp("o_" + cid, cid, PAR, PS[stage], status=status, changed=changed, name=place, company=place))

    partner("p1", 1, "Northside Hospital, Case Management", "no_answer", "hospital", changed=at(days=10),
            whisper="A large hospital desk. Ask for case management. Main line [number].")
    MS.append(msg("p1", "TYPE_CAMPAIGN_CALL", "outbound", at(days=10), status="completed", dur=0, cst="no-answer",
                  source="workflow"))
    partner("p2", 2, "Eastside Rehab", "to_call", "inpatient-rehab")
    partner("p3", 3, "Westside Nursing (main desk)", "talked", "nursing-home", changed=at(days=20))
    MS.append(msg("p3", "TYPE_CALL", "outbound", at(days=20), status="completed", dur=75, cst="completed", source="app"))
    partner("p4", 4, "Southside Hospice", "info_sent", "hospice", email="desk@example.com", tags=["open-beds-weekly"],
            changed=at(days=12))
    MS += [msg("p4", "TYPE_CALL", "outbound", at(days=3), status="completed", dur=40, cst="completed", source="app"),
           msg("p4", "TYPE_EMAIL", "outbound", at(days=5), status="sent", source="app",
               subject="Private and shared rooms this week", body="<p>Hi there</p>")]
    partner("p5", 5, "Central Agency", "yes", "area-agency-on-aging", changed=at(days=9))
    partner("p6", 6, "Harbor Social Work", "referral", "other", email="sw@example.com", tags=["open-beds-weekly"],
            changed=at(days=4))
    MS += [msg("p6", "TYPE_EMAIL", "outbound", at(days=5), status="sent", source="app", subject="Discharges this week?",
               body="<p>Hello</p>"),
           msg("p6", "TYPE_EMAIL", "inbound", at(days=3), body="We may have someone next week. Call me at 555 400 0006.",
               subject="Re: Discharges this week?")]
    partner("p7", 7, "Lakeside Clinic", "not_fit", "other", status="lost", changed=at(days=15))
    # a partner whose deal sits in the FAMILY pipeline (the AGC collector's bug case): still a partner, never a family
    C.append(contact("p8", "", "", phone="+15554000008", company="Ridge Hospital", added=at(days=30),
                     tags=["referral-partner", "partner-hospital"]))
    O.append(opp("o_p8", "p8", FAM, FS["qual"], changed=at(days=30)))

    # not a family
    C.append(contact("job1", "", "", phone="+15556000001", added=at(days=12), fields=cf(agent_stage="not a family: job seeker")))

    # unknown callers (no name, not judged yet)
    greet = [{"mediaChannel": 1, "transcript": "Hey."}, {"mediaChannel": 1, "transcript": "This is Joey from Sample Grove Home."},
             {"mediaChannel": 1, "transcript": "Hello?"}, {"mediaChannel": 1, "transcript": "Hello?"}]

    def unknown(cid, phone, added, calls, texts=()):
        C.append(contact(cid, "", "", phone=phone, added=added, fields=cf(agent_stage="new") if cid.endswith("n") else []))
        for c in calls:
            m = msg(cid, "TYPE_CALL", "inbound", c["when"], status=c["st"], dur=c.get("dur"), cst=c["st"],
                    rec=c.get("rec", True))
            MS.append(m)
            if c.get("tx") is not None:
                TX[m["id"]] = c["tx"]
        for t in texts:
            MS.append(msg(cid, "TYPE_SMS", "inbound", t["when"], status="delivered", body=t["body"]))

    unknown("u1", "+15552010001", at(days=2), [{"when": at(days=2), "st": "completed", "dur": 20, "tx": greet}])
    unknown("u2n", "+15552010002", at(days=3), [{"when": at(days=3), "st": "completed", "dur": 18, "tx": greet}])
    unknown("u3", "+15557773003", at(days=4), [{"when": at(days=4), "st": "completed", "dur": 45, "tx": greet[:2] + [
        {"mediaChannel": 2, "transcript": "Hi, I am looking for a place for my mom."},
        {"mediaChannel": 2, "transcript": "She needs help with bathing."}]}])
    unknown("u4", "+15558884004", at(days=5), [{"when": at(days=5), "st": "completed", "dur": 30, "tx": greet[:2] + [
        {"mediaChannel": 1, "transcript": "I was calling to see if you are hiring caregivers."}]}])
    unknown("u5", "+15559995005", at(days=6), [{"when": at(days=6), "st": "voicemail", "dur": 25}])
    unknown("u6", "+15551116006", at(days=6), [{"when": at(days=6), "st": "no-answer", "rec": False}],
            texts=[{"when": at(days=6, minutes=-5), "body": "Hi, is there a room for my dad?"}])
    for k in range(3):   # a wave: three new numbers from one area code inside 30 minutes, nobody answered
        unknown("w%d" % k, "+1444555%04d" % (1000 + k * 37), at(days=1, minutes=10 * k),
                [{"when": at(days=1, minutes=10 * k), "st": "no-answer", "rec": False}])
    unknown("old1", "+15551237007", at(days=30), [{"when": at(days=30), "st": "completed", "dur": 12, "tx": greet}])

    pipelines = [
        {"id": FAM, "name": "FBF | Family Journey", "stages": [
            {"id": FS["engaged"], "name": "Engaged Conversation"}, {"id": FS["qual"], "name": "Qualification In Progress"},
            {"id": FS["tour_booked"], "name": "Tour Booked"}, {"id": FS["attended"], "name": "Tour Attended"},
            {"id": FS["post_tour"], "name": "Post-Tour Follow-Up"}, {"id": FS["move_in"], "name": "Move-In Pending"}]},
        {"id": PAR, "name": "Referral Partners", "stages": [
            {"id": PS["to_call"], "name": "To Call"}, {"id": PS["no_answer"], "name": "No Answer"},
            {"id": PS["talked"], "name": "Talked"}, {"id": PS["yes"], "name": "Yes Partner"},
            {"id": PS["info_sent"], "name": "Info Sent"}, {"id": PS["referral"], "name": "Sent a Referral"},
            {"id": PS["not_fit"], "name": "Not a Fit"}]},
    ]
    return {"contacts": C, "opportunities": O, "messages": MS, "events": EV, "transcripts": TX, "pipelines": pipelines}


def write_fake_dir(path, drop=(), data=None):
    d = data or build()
    os.makedirs(path, exist_ok=True)
    files = {
        "contacts": {"contacts": d["contacts"][:1], "total": len(d["contacts"])},
        "locations__" + LOC: {"location": {"id": LOC, "name": "Sample Grove Home", "city": "Springfield", "state": "MI",
                                           "website": "https://samplegrove.example.com/", "timezone": "America/New_York",
                                           "phone": HOME_PHONE, "email": "home@example.org"}},
        "users": {"users": [{"id": "u_joey", "phone": USER_PHONE, "email": "joey@example.net",
                             "lcPhone": {LOC: "+15550108888"}}]},
        "opportunities__pipelines": {"pipelines": d["pipelines"]},
        "locations__%s__customFields" % LOC: {"customFields": [{"id": fid, "name": FIELD_NAMES[k]} for k, fid in F.items()]},
        "calendars": {"calendars": [{"id": TOUR, "name": "Tour Calendar", "isActive": True},
                                    {"id": "cal_x", "name": "Someone's Personal Calendar", "isActive": True}]},
        "contacts__search": {"contacts": d["contacts"], "total": len(d["contacts"])},
        "opportunities__search": {"opportunities": d["opportunities"], "meta": {"total": len(d["opportunities"])}},
        "calendars__events": {"events": d["events"]},
        "conversations__messages__export": {"messages": d["messages"], "total": len(d["messages"])},
    }
    # the conversations API: one search page, then one messages page per conversation (newest first)
    convs = {}
    for m in d["messages"]:
        convs.setdefault(m["conversationId"], []).append(m)
    # Harbor Social Work's email and its reply come back as one thread row with two email ids and no direction,
    # the way the live conversations API folds a reply onto the email it answers.
    hv = convs.get("cv_p6") or []
    em = sorted([m for m in hv if m["messageType"] == "TYPE_EMAIL"], key=lambda m: m["dateAdded"])
    if len(em) == 2:
        for m in em:
            files["conversations__messages__email__e_" + m["id"]] = {"emailMessage": {
                "id": "e_" + m["id"], "contactId": "p6", "direction": m["direction"], "dateAdded": m["dateAdded"],
                "status": m.get("status"), "source": m.get("source"), "subject": m.get("subject"), "body": m.get("body")}}
        thread = dict(em[-1], direction=None, meta={"email": {"messageIds": ["e_" + m["id"] for m in em]}})
        convs["cv_p6"] = [m for m in hv if m["messageType"] != "TYPE_EMAIL"] + [thread]
    rows = []
    for cv, ms in convs.items():
        ms = sorted(ms, key=lambda m: m["dateAdded"], reverse=True)
        newest = dt.datetime.fromisoformat(ms[0]["dateAdded"].replace("Z", "+00:00"))
        rows.append({"id": cv, "contactId": ms[0]["contactId"], "lastMessageDate": int(newest.timestamp() * 1000),
                     "sort": [int(newest.timestamp() * 1000)]})
        files["conversations__%s__messages" % cv] = {"messages": {"messages": ms, "nextPage": False,
                                                                  "lastMessageId": ms[-1]["id"]}}
    rows.sort(key=lambda r: -r["lastMessageDate"])
    files["conversations__search"] = {"conversations": rows, "total": len(rows)}
    for mid, segs in d["transcripts"].items():
        files["conversations__locations__%s__messages__%s__transcription" % (LOC, mid)] = segs
    for name, obj in files.items():
        if name in drop:
            continue
        with open(os.path.join(path, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    return path
