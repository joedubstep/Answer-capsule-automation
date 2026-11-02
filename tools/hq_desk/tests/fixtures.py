"""Synthetic GoHighLevel data for the HQ desk tests. Every person, home, phone and email here is made up.

The shapes copy what the live API returns (checked read-only against the AGC location on 2026-11-02) and the
pipeline, stage and field ids copy Surven HQ's structure (scratchpad hq_probe.txt, config/surven.json).
write_fake_dir(path) writes one JSON file per GET path, the way shared.ghl's GHL_FAKE_DIR hook reads them.
"""
import datetime as dt
import json
import os

NOW = dt.datetime(2026, 11, 2, 11, 0, tzinfo=dt.timezone.utc)      # Mon Nov 2, 6:00am ET
LOC = "EeadFhXhDOJ1DWE4ArhK"
CAL = "siNHUDan1hhV6eKLstdq"
LS, EM, WR, NL = "WN4pEbi1zNUn7icsObpN", "D26Fys9N44CiadqYjkm7", "XxLNrcg6PpnhCMkPvJ1C", "lscmkVBQStUnDgscgNvP"

ST = {
    "new_lead": "15724b78-3a1b-448c-b014-dfdbd387011a", "no_answer": "04c30041-8199-47ad-806b-cbe900ab9abc",
    "call_back": "22d45f7b-8ad5-4472-bb43-b20f40578907", "scheduled": "9ac5a196-fbdb-44ae-b36c-39addf082298",
    "confirmed": "6a864718-7db4-49e3-8711-4a08fe7c41c6", "no_show": "8d02157f-93fe-466d-a4c1-3ae9a7ce0e76",
    "follow_up": "30b7ef97-4227-41a5-87fd-39e38d632459", "ls_replied": "350ecf76-dd4e-4f62-9e47-abf9ffc92630",
    "wrong_timing": "0ec091f2-821d-474c-9e1f-4d1d65dfc68b", "not_interested": "31890f5b-66dc-40e4-9727-8ef076bda535",
    "em_replied": "2d72401c-7e3b-47ad-9444-a38ea1a91e3e", "em_talked": "55d83694-1c05-40a6-b7e6-5ce931fcf1a1",
    "wr_new": "0d122193-43ce-4675-9958-2864f59d7f31", "wr_booked": "a3d49088-7329-4192-9e6b-c38dfabfbcc8",
}

FIELDS = {  # Surven HQ contact field ids and names (system ids, no personal data)
    "AKYFgsLdEpgWkH8ATZOZ": "Agent Promises Owed", "5uekZTIesjrsq4qXmTva": "Agent Contact Picture",
    "IMwscFpwXhfOSxY0XavX": "Agent Plan Log", "SVbKsBw2h3f977KHH9mT": "Agent Next Touch",
    "K82Od07lPi89b2qXkDTS": "Agent Stage", "S3wYC4TuoY67XM3Q75MT": "Agent Whisper",
    "R1oLEswNp6xA4S9mR1gx": "Agent Preferred Name", "5qNYXRzPs55rPUtRwoxD": "Reply Code",
    "6pUnUwaxqRfQW3q0g2AR": "Email Reply Code", "Ljgi8lrRnBspiBCkUGMw": "Total Beds",
    "7qPloM1ghvJyYx5sMG2p": "Community Type", "5Jf00IKn2synrPTufwBB": "SURVEN Contact Timezone",
    "ZzZnJIRyTgTBb5VYffg0": "Test Contact", "S8XwLPke4oVq9cywNpuL": "Global Suppressed",
}
F = {name: fid for fid, name in FIELDS.items()}


def ago(hours=0, days=0):
    return (NOW - dt.timedelta(hours=hours, days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ahead(days):
    return (NOW + dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def cf(**kv):
    names = {"owed": "Agent Promises Owed", "picture": "Agent Contact Picture", "log": "Agent Plan Log",
             "next": "Agent Next Touch", "stage": "Agent Stage", "whisper": "Agent Whisper",
             "code": "Reply Code", "ecode": "Email Reply Code", "beds": "Total Beds", "community": "Community Type",
             "test": "Test Contact"}
    return [{"id": F[names[k]], "value": v} for k, v in kv.items()]


def contact(cid, first, last, home="", tags=(), fields=None):
    return {"id": cid, "firstName": first, "lastName": last, "companyName": home, "tags": list(tags),
            "email": first.lower() + "@example.com", "phone": "+15550100" + str(len(cid) % 10) + "0",
            "dateAdded": ago(days=20), "customFields": fields or []}


def opp(oid, cid, name, pipe, stage, status="open", created=None, changed=None, tags=()):
    return {"id": oid, "name": name, "pipelineId": pipe, "pipelineStageId": ST[stage], "status": status,
            "contactId": cid, "createdAt": created or ago(days=15), "updatedAt": changed or ago(days=1),
            "lastStageChangeAt": changed or ago(days=3), "lastStatusChangeAt": created or ago(days=15),
            "monetaryValue": 0, "contact": {"id": cid, "name": name, "companyName": "", "tags": list(tags),
                                            "email": "x@example.com", "phone": "+15550109999"}}


def msg(mid, when, direction, mtype, source=None, status="delivered", body=None, email_dir=None, subject=None):
    m = {"id": mid, "dateAdded": when, "messageType": mtype, "status": status, "source": source,
         "type": {"TYPE_SMS": 2, "TYPE_EMAIL": 3}.get(mtype, 1)}
    if direction:
        m["direction"] = direction
    if body is not None:
        m["body"] = body
    if mtype == "TYPE_EMAIL":
        m["meta"] = {"email": {"direction": email_dir or direction, "subject": subject or "Re: open beds",
                               "messageIds": [mid + "-e"]}}
    return m


CONTACTS = [
    contact("cHot0001", "Pat", "Example", "Maple Example Home", ["leadsuite"],
            cf(code="41", beds="12", community="Assisted Living", stage="talking",
               picture="Asked for: afternoons (10/30 call). Waiting on us: none. Situation: 12 beds, 4 empty.")),
    contact("cDecide02", "Sam", "Sample", "Oak Sample Residence", ["leadsuite", "price-raise"],
            cf(code="12", beds="8", stage="thinking it over", owed="2026-10-20: send the case study Loom",
               log="2026-11-01: thinking it over, waiting on Loom\n2026-10-31: texted, no reply",
               picture=("Asked for: texts first (10/27 call). Waiting on us: Loom with case studies, promised 10/20, "
                        "Joey; licensing question for Example County, since 10/28, Joey. Situation: 8 beds, 3 empty "
                        "since August. Offer 10/27 call: $4,500 for 90 days, ad spend $60/day. Zone: Central."))),
    contact("cNoShow03", "Lee", "Placeholder", "Birch Placeholder Care", ["leadsuite"],
            cf(code="7", stage="no-show")),
    contact("cReply004", "Alex", "Demo", "", ["email-reply"], cf(ecode="24", beds="20")),
    contact("cWarm0005", "Jordan", "Sample", "Cedar Sample House", ["referral"], cf()),
    contact("cTest0006", "Test", "Person", "", ["svn-test"], cf(code="99")),
    contact("cPark0007", "Casey", "Example", "Pine Example Manor", ["leadsuite"],
            cf(code="30", stage="parked until 2026-12-01", owed="2026-12-01: home opens Dec 1, check back")),
    contact("cBook0008", "Robin", "Example", "Elm Example Living", ["leadsuite"], cf(code="55", stage="booked")),
    contact("cDone0009", "Drew", "Example", "Ash Example Home", ["leadsuite"], cf(code="60", stage="talking")),
]

OPPS = [
    opp("o1", "cHot0001", "Pat Example", LS, "call_back"),
    opp("o2", "cDecide02", "Sam Sample", LS, "follow_up", changed=ago(days=6), tags=["price-raise"]),
    opp("o3", "cNoShow03", "Lee Placeholder", LS, "no_show", changed=ago(days=3)),
    opp("o4", "cReply004", "Alex Demo", EM, "em_replied", created=ago(days=4)),
    opp("o5", "cWarm0005", "Jordan Sample", WR, "wr_new", created=ago(days=5)),
    opp("o6", "cTest0006", "Test Person", LS, "call_back"),
    opp("o7", "cPark0007", "Casey Example", LS, "wrong_timing"),
    opp("o8", "cBook0008", "Robin Example", LS, "confirmed"),
    opp("o9", "cDone0009", "Drew Example", LS, "call_back"),
    opp("o10", "cLost0010", "Kim Example", LS, "not_interested", status="lost", created=ago(days=2)),
]

CONVS = {
    "cHot0001": ("vHot", [
        msg("h4", ago(hours=4), "outbound", "TYPE_SMS", source="workflow", body="Thanks, we got your message."),
        msg("h3", ago(hours=5), "inbound", "TYPE_SMS",
            body="Can you call me after 3? My cell is 555-201-4477 or pat@example.com"),
        msg("h2", ago(hours=50), "outbound", "TYPE_SMS", source="app", body="Are the 4 open beds for elderly residents?"),
        msg("h1", ago(hours=52), "inbound", "TYPE_SMS", body="We have 4 empty beds."),
    ]),
    "cDecide02": ("vDecide", [
        msg("d3", ago(days=3), "outbound", "TYPE_SMS", source="app", body="Any questions on the plan?"),
        msg("d2", ago(days=4), "inbound", "TYPE_SMS", body="Still thinking. Need to talk with my partner."),
        msg("d1", ago(days=6), "outbound", "TYPE_ACTIVITY_OPPORTUNITY", source="app", status=None),
    ]),
    "cNoShow03": ("vNoShow", [
        msg("n1", ago(days=2), "outbound", "TYPE_CAMPAIGN_CALL", source="workflow", status="no-answer"),
    ]),
    "cReply004": ("vReply", [
        msg("r1", ago(days=4), None, "TYPE_EMAIL", email_dir="inbound",
            body=("<p>Yes, we have 3 open beds. What does it cost?</p><p>On Mon, Oct 26, 2026 at 9:00 AM Joey "
                  "wrote:</p><blockquote>&gt; older text</blockquote>")),
    ]),
    "cTest0006": ("vTest", [msg("t1", ago(hours=2), "inbound", "TYPE_SMS", body="test")]),
    "cPark0007": ("vPark", [
        msg("p2", ago(hours=29), "outbound", "TYPE_SMS", source="app", body="Okay, talk in December."),
        msg("p1", ago(hours=30), "inbound", "TYPE_SMS", body="We open in December."),
    ]),
    "cBook0008": ("vBook", [msg("b1", ago(days=1), "outbound", "TYPE_CALL", source="app", status="completed")]),
    "cDone0009": ("vDone", [
        msg("x2", ago(hours=19), "outbound", "TYPE_SMS", source="app", body="Okay, Thursday works."),
        msg("x1", ago(hours=20), "inbound", "TYPE_SMS", body="Thursday is better for me."),
    ]),
}

EVENTS = [
    {"id": "e1", "calendarId": CAL, "contactId": "cDecide02", "startTime": ago(days=6), "endTime": ago(days=6),
     "appointmentStatus": "confirmed", "deleted": False, "title": "Discovery Call | Joey x Sam"},
    {"id": "e2", "calendarId": CAL, "contactId": "cNoShow03", "startTime": ago(days=3), "endTime": ago(days=3),
     "appointmentStatus": "noshow", "deleted": False, "title": "Discovery Call | Joey x Lee"},
    {"id": "e3", "calendarId": CAL, "contactId": "cBook0008", "startTime": ahead(3), "endTime": ahead(3),
     "appointmentStatus": "confirmed", "deleted": False, "title": "Discovery Call | Joey x Robin"},
    {"id": "e4", "calendarId": CAL, "contactId": "cDone0009", "startTime": ahead(2), "endTime": ahead(2),
     "appointmentStatus": "cancelled", "deleted": False, "title": "Discovery Call | Joey x Drew"},
    {"id": "e5", "calendarId": "otherCalendar", "contactId": "cDone0009", "startTime": ahead(1),
     "endTime": ahead(1), "appointmentStatus": "confirmed", "deleted": False, "title": "Other calendar"},
]


def pipelines():
    def p(pid, name, stages):
        return {"id": pid, "name": name, "stages": [{"id": ST.get(k, k), "name": n} for k, n in stages]}
    return {"pipelines": [
        p(LS, "Leadsuite Pipeline", [("new_lead", "New Lead"), ("no_answer", "Call - No Answer"),
                                     ("call_back", "Call Back"), ("scheduled", "Meeting Scheduled"),
                                     ("confirmed", "Confirmed"), ("no_show", "No Show"), ("follow_up", "Follow Up"),
                                     ("not_interested", "Not Interested"), ("ls_replied", "Replied"),
                                     ("wrong_timing", "Wrong Timing")]),
        p(EM, "Email Pipeline", [("em_replied", "Replied"), ("em_talked", "Talked")]),
        p(WR, "Warm Referral", [("wr_new", "New"), ("wr_booked", "Meeting Booked")]),
        p(NL, "Normal Lead", [("nl_new", "New Lead")]),
    ]}


def files():
    out = {
        "contacts.json": {"contacts": [], "total": 0},
        "opportunities__pipelines.json": pipelines(),
        f"locations__{LOC}__customFields.json": {"customFields": [{"id": k, "name": v} for k, v in FIELDS.items()]},
        "opportunities__search.json": {"opportunities": OPPS, "meta": {"total": len(OPPS)}},
        "conversations__search.json": {"conversations": [
            {"id": cv, "contactId": cid, "type": "TYPE_PHONE", "lastMessageDate": 1, "lastMessageDirection": "inbound",
             "lastMessageType": "TYPE_SMS", "unreadCount": 0} for cid, (cv, _) in CONVS.items()]},
        "calendars__events.json": {"events": EVENTS},
    }
    for c in CONTACTS:
        out[f"contacts__{c['id']}.json"] = {"contact": c}
    for cid, (cv, msgs) in CONVS.items():
        out[f"conversations__{cv}__messages.json"] = {"messages": {"lastMessageId": msgs[-1]["id"], "nextPage": False,
                                                                     "messages": msgs}}
    return out


def write_fake_dir(path, drop=()):
    os.makedirs(path, exist_ok=True)
    for name, obj in files().items():
        if name in drop:
            continue
        with open(os.path.join(path, name), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    return path


def profile():
    return {"key": "hq", "location": LOC,
            "pipelines": [{"key": "email", "id": EM}, {"key": "leadsuite", "id": LS},
                          {"key": "warm_referral", "id": WR}, {"key": "normal_lead", "id": NL}],
            "meeting_calendar": CAL, "joey_contact": "ITgRAUyt3KqdPbQB5cUo",
            "deadline_et": "2026-11-18T20:00", "artifact_url": "https://claude.ai/artifact/example",
            "skip_codes": [], "default_field_ids": {}}
