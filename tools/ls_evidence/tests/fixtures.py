"""Synthetic Surven HQ GoHighLevel data for the Lead Suite Evidence tests. Every person, phone and email here is made
up. Shapes copy what the live API returns (checked read-only against the AGC location on 2026-11-02); the pipeline,
calendar and field ids copy Surven HQ's structure (scratchpad hq_probe.txt). The SMS, pre-call, lead replied and
meeting brief fields get made-up ids on purpose, so the tests prove those are found by key or name at run time.

write_fake_dir(path) writes one JSON file per GET path, the way shared.ghl's GHL_FAKE_DIR hook reads them.

Each lead is built to test one or two rules (expected box answers in portal order: Y yes, N no, - not due, ? unknown):
  Pat 41     perfect ladder, never replies                                   YY-YYN
  Sam 12     SMS 1 late, replies by text, double dial, booked, showed        YNY--Y   call YYYYY
  Lee 7      after hours on the night DST ends; SMS 2 early (DST trap)      YY-NYN
  Alex 30    STL fields filled, no messages (field wins, check flagged)      YN-NNN
  Robin 55   came back through the form; 2 dials; missed call in; Wrong Fit NYN--Y   call NNNN? (not qualified)
  Casey 60   replies, call back answered; cancel and rebook; call ahead      YYY--Y   call waiting
  Drew 70    test tag (left out)
  Kim 80     same phone as Pat (duplicate)
  Jordan 90  came in an hour ago in quiet hours (everything still due)
  Morgan 99  contact from before ads went live (left out)
  Taylor 95  only in the pipeline (no tag); Central time; auto-dial answered, length from transcript;
             pre-call email at 4:30pm Central the day DST ended (No); no-show                        call YNNYN
"""
import datetime as dt
import json
import os

NOW = dt.datetime(2026, 11, 8, 11, 0, tzinfo=dt.timezone.utc)       # Sun Nov 8, 6:00am EST (the weekly run)
LOC = "EeadFhXhDOJ1DWE4ArhK"
LS = "WN4pEbi1zNUn7icsObpN"
DISC, LSCAL = "siNHUDan1hhV6eKLstdq", "TfETBEfg6aye6PYNdYZX"

ST = {"new_lead": "15724b78-3a1b-448c-b014-dfdbd387011a", "no_answer": "04c30041-8199-47ad-806b-cbe900ab9abc",
      "scheduled": "9ac5a196-fbdb-44ae-b36c-39addf082298", "no_show": "8d02157f-93fe-466d-a4c1-3ae9a7ce0e76",
      "follow_up": "30b7ef97-4227-41a5-87fd-39e38d632459", "unqualified": "8cabaa7a-0ca4-4183-90aa-2d8f50f8314e",
      "replied": "350ecf76-dd4e-4f62-9e47-abf9ffc92630"}
STAGE_NAMES = {"new_lead": "New Lead", "no_answer": "Call - No Answer", "scheduled": "Meeting Scheduled",
               "no_show": "No Show", "follow_up": "Follow Up", "unqualified": "Unqualified", "replied": "Replied"}

FIELDS = [  # (id, name, fieldKey). Made-up ids for the fields the probe did not list.
    ("ntJnTEIUoaeilJ8CSGM2", "STL Lead In At", "contact.stl_lead_in_at"),
    ("csuyMrDdyfTQjnLh6Cvp", "STL First Dial At", "contact.stl_first_dial_at"),
    ("Joxd7amkJniU3raFVIcr", "STL Triple Dial Done", "contact.stl_triple_dial_done"),
    ("fakeSms1Field000001", "STL SMS1 In 5min", "contact.stl_sms1_in_5min"),
    ("fakeSms2Field000002", "STL SMS2 Done", "contact.stl_sms2_done"),
    ("fakeSms3Field000003", "STL SMS3 Done", "contact.stl_sms3_done"),
    ("kXDbOuYIUHJOZxhyelsJ", "STL Double Dial After Reply", "contact.stl_double_dial_after_reply"),
    ("fakeReplField000004", "STL Lead Replied", "contact.stl_lead_replied"),
    ("Xt2ntxZudC5aCNLmBLvI", "STL Triage Call Done", "contact.stl_triage_call_done"),
    ("fakePreField0000005", "STL Precall Email Sent", "contact.stl_precall_email_sent"),
    ("eC34ROlcXVSFxqXLojEp", "STL Morning Confirm Done", "contact.stl_morning_confirm_done"),
    ("EXZllTjaS8yVem0Uis83", "STL Showed", "contact.stl_showed"),
    ("7HbD1JFZPREDt5SAueOA", "STL No-Show Count", "contact.stl_noshow_count"),
    ("uNxv8vTnlnaWxCJlGq9q", "STL Outcome Reason", "contact.stl_outcome_reason"),
    ("5qNYXRzPs55rPUtRwoxD", "Reply Code", "contact.reply_code"),
    ("fakeBriefField00006", "Agent Meeting Brief", "contact.agent_meeting_brief"),
    ("ZzZnJIRyTgTBb5VYffg0", "Test Contact", "contact.test_contact"),
    ("5Jf00IKn2synrPTufwBB", "SURVEN Contact Timezone", "contact.surven__contact_timezone"),
]
F = {name: fid for fid, name, _ in FIELDS}


def cf(**kv):
    names = {"code": "Reply Code", "lead_in": "STL Lead In At", "triple": "STL Triple Dial Done",
             "sms1": "STL SMS1 In 5min", "reason": "STL Outcome Reason", "brief": "Agent Meeting Brief",
             "test": "Test Contact", "showed": "STL Showed"}
    return [{"id": F[names[k]], "value": v} for k, v in kv.items()]


def contact(cid, first, last, added, phone, tags=("leadsuite",), fields=None, tz=""):
    return {"id": cid, "firstName": first, "lastName": last, "contactName": f"{first} {last}".lower(),
            "email": first.lower() + "@example.com", "phone": phone, "tags": list(tags), "dateAdded": added,
            "timezone": tz, "dnd": False, "customFields": fields or [], "companyName": ""}


def opp(oid, cid, stage, created, status="open"):
    return {"id": oid, "name": "x", "pipelineId": LS, "pipelineStageId": ST[stage], "status": status,
            "contactId": cid, "createdAt": created, "updatedAt": created, "monetaryValue": 0,
            "contact": {"id": cid, "name": "x", "phone": "+15550109999", "email": "x@example.com", "tags": []}}


def msg(mid, cid, when, direction, mtype, status="delivered", source="app", duration=None, subject=None, body=None):
    m = {"id": mid, "contactId": cid, "dateAdded": when, "messageType": mtype, "status": status, "source": source,
         "type": {"TYPE_CALL": 1, "TYPE_SMS": 2, "TYPE_EMAIL": 3, "TYPE_CAMPAIGN_CALL": 8}.get(mtype, 0)}
    if direction:
        m["direction"] = direction
    if mtype in ("TYPE_CALL", "TYPE_CAMPAIGN_CALL") and (duration is not None or mtype == "TYPE_CALL"):
        m["meta"] = {"call": {"duration": duration, "status": status}}
    if mtype == "TYPE_EMAIL":
        m["meta"] = {"email": {"direction": direction, "subject": subject or "", "messageIds": [mid + "-e"]}}
        m.pop("direction", None)          # the live API often leaves direction off emails
        m.pop("status", None)
    if body is not None:
        m["body"] = body
    return m


CC, SMS, EM, CALL = "TYPE_CAMPAIGN_CALL", "TYPE_SMS", "TYPE_EMAIL", "TYPE_CALL"
OUT, IN = "outbound", "inbound"

CONTACTS = [
    contact("cPat00001", "Pat", "Example", "2026-10-19T14:00:00.000Z", "+15550100001", fields=cf(code="41")),
    contact("cSam00002", "Sam", "Sample", "2026-10-20T15:00:00.000Z", "+15550100002", fields=cf(code="12")),
    contact("cLee00003", "Lee", "Placeholder", "2026-11-01T03:30:00.000Z", "+15550100003", fields=cf(code="7"),
            tz="America/New_York"),
    contact("cAlex0004", "Alex", "Demo", "2026-06-10T12:00:00.000Z", "+15550100004",
            fields=cf(code="30", lead_in="2026-10-22T13:00:00.000Z", triple="Yes", sms1=["No"])),
    contact("cRob00005", "Robin", "Example", "2026-06-01T12:00:00.000Z", "+15550100005",
            fields=cf(code=55, reason="Wrong Fit", brief="Loved one: none yet. Home has 6 beds. Asked about families "
                                                         "from the hospital.")),
    contact("cCas00006", "Casey", "Example", "2026-11-06T14:00:00.000Z", "+15550100006", fields=cf(code="60")),
    contact("cDrew0007", "Drew", "Example", "2026-10-25T14:00:00.000Z", "+15550100007", tags=("leadsuite", "svn-test"),
            fields=cf(code="70")),
    contact("cKim00008", "Kim", "Example", "2026-10-21T14:00:00.000Z", "(555) 010-0001", fields=cf(code="80")),
    contact("cJor00009", "Jordan", "Sample", "2026-11-08T10:00:00.000Z", "+15550100009", fields=cf(code="90")),
    contact("cMor00010", "Morgan", "Example", "2026-07-30T12:00:00.000Z", "+15550100010", fields=cf(code="99")),
]
TAYLOR = contact("cTay00011", "Taylor", "Example", "2026-10-29T14:00:00.000Z", "+15550100011", tags=("facebook lead",),
                 fields=cf(code="95"), tz="America/Chicago")
NOISE = contact("cNoise012", "Noah", "Other", "2026-10-29T14:00:00.000Z", "+15550100012", tags=("referral",))

OPPS = [
    opp("o1", "cPat00001", "no_answer", "2026-10-19T14:00:05.000Z"),
    opp("o2", "cSam00002", "follow_up", "2026-10-20T15:00:05.000Z"),
    opp("o3", "cLee00003", "no_answer", "2026-11-01T03:30:05.000Z"),
    opp("o5", "cRob00005", "scheduled", "2026-10-26T14:00:00.000Z"),
    opp("o6", "cCas00006", "scheduled", "2026-11-06T14:00:05.000Z"),
    opp("o11", "cTay00011", "no_show", "2026-10-29T14:00:05.000Z"),
]

CONVS = {
    "cPat00001": ("vPat", [
        msg("p0", "cPat00001", "2026-10-19T14:00:30.000Z", OUT, CC, "canceled", "workflow"),   # bridge never reached her
        msg("p1", "cPat00001", "2026-10-19T14:01:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("p2", "cPat00001", "2026-10-19T14:02:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("p3", "cPat00001", "2026-10-19T14:03:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("p4", "cPat00001", "2026-10-19T14:04:00.000Z", OUT, CC, "voicemail", "workflow"),
        msg("p5", "cPat00001", "2026-10-19T17:20:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("p6", "cPat00001", "2026-10-19T19:50:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
    ]),
    "cSam00002": ("vSam", [
        msg("s1", "cSam00002", "2026-10-20T15:01:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("s2", "cSam00002", "2026-10-20T15:02:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("s3", "cSam00002", "2026-10-20T15:03:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("s4", "cSam00002", "2026-10-20T15:06:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("s5", "cSam00002", "2026-10-20T15:30:00.000Z", IN, SMS, "delivered", None, body="Yes call me, 555-201-4477"),
        msg("s6", "cSam00002", "2026-10-20T15:32:00.000Z", OUT, CALL, "no-answer"),
        msg("s7", "cSam00002", "2026-10-20T15:35:00.000Z", OUT, CALL, "completed", duration=600),
        msg("s8", "cSam00002", "2026-10-20T15:41:00.000Z", OUT, SMS, "delivered", "workflow", body="booked"),
        msg("s9", "cSam00002", "2026-10-21T22:30:00.000Z", OUT, EM, subject="SURVEN [REQUIRED-URGENT] Watch this first"),
        msg("s10", "cSam00002", "2026-10-22T13:00:00.000Z", OUT, CALL, "no-answer"),
        msg("s11", "cSam00002", "2026-10-22T13:05:00.000Z", OUT, SMS, "delivered", body="see you at 2"),
    ]),
    "cLee00003": ("vLee", [
        msg("l1", "cLee00003", "2026-11-01T13:01:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("l2", "cLee00003", "2026-11-01T13:02:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("l4", "cLee00003", "2026-11-01T13:03:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("l3", "cLee00003", "2026-11-01T13:04:00.000Z", OUT, CC, "voicemail", "workflow"),
        msg("l5", "cLee00003", "2026-11-01T15:30:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("l6", "cLee00003", "2026-11-01T18:30:00.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
    ]),
    "cRob00005": ("vRob", [
        msg("r1", "cRob00005", "2026-10-26T14:01:00.000Z", OUT, CALL, "no-answer"),
        msg("r2", "cRob00005", "2026-10-26T14:02:00.000Z", OUT, CALL, "busy"),
        msg("r3", "cRob00005", "2026-10-26T14:02:30.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("r4", "cRob00005", "2026-10-26T14:10:00.000Z", IN, CALL, "no-answer", None),
        msg("r5", "cRob00005", "2026-10-26T14:12:00.000Z", OUT, CALL, "no-answer"),
    ]),
    "cCas00006": ("vCas", [
        msg("c1", "cCas00006", "2026-11-06T14:01:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("c2", "cCas00006", "2026-11-06T14:02:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("c4", "cCas00006", "2026-11-06T14:02:30.000Z", OUT, SMS, "delivered", "workflow", body="hi"),
        msg("c3", "cCas00006", "2026-11-06T14:03:00.000Z", OUT, CC, "no-answer", "workflow"),
        msg("c5", "cCas00006", "2026-11-06T14:20:00.000Z", IN, SMS, "delivered", None, body="ok"),
        msg("c6", "cCas00006", "2026-11-06T14:21:00.000Z", OUT, CALL, "completed", duration=240),
        msg("c7", "cCas00006", "2026-11-06T14:46:00.000Z", OUT, SMS, "delivered", "workflow", body="booked"),
    ]),
    "cTay00011": ("vTay", [
        msg("t1", "cTay00011", "2026-10-29T14:02:00.000Z", OUT, CC, "completed", "workflow"),     # no length in GHL
        msg("t2", "cTay00011", "2026-10-29T14:10:00.000Z", OUT, SMS, "delivered", "workflow", body="booked"),
        msg("t3", "cTay00011", "2026-11-01T22:30:00.000Z", OUT, EM, subject="SURVEN [REQUIRED-URGENT] Before our call"),
        msg("t4", "cTay00011", "2026-11-02T13:30:00.000Z", OUT, SMS, "delivered", "workflow", body="today"),
    ]),
    "cJor00009": ("vJor", []),
}
TRANSCRIPTS = {"t1": [{"sentenceIndex": i, "transcript": " ".join(["word"] * 20), "speaker": 1, "startTime": i,
                       "endTime": i + 1, "mediaChannel": 1, "words": []} for i in range(10)]}     # 200 words

EVENTS = [
    {"id": "eSam", "calendarId": DISC, "contactId": "cSam00002", "startTime": "2026-10-22T14:00:00-04:00",
     "endTime": "2026-10-22T14:30:00-04:00", "dateAdded": "2026-10-20T15:40:00.000Z", "appointmentStatus": "showed",
     "deleted": False, "title": "Discovery Call | Joey x Sam", "createdBy": {"source": "mobile_app"}},
    {"id": "eSamCopy", "calendarId": LSCAL, "contactId": "cSam00002", "startTime": "2026-10-22T14:00:00-04:00",
     "endTime": "2026-10-22T14:30:00-04:00", "dateAdded": "2026-10-20T15:41:00.000Z", "appointmentStatus": "confirmed",
     "deleted": False, "title": "Discovery Call | Joey x Sam", "createdBy": {"source": "google_calendar"}},
    {"id": "eRob", "calendarId": DISC, "contactId": "cRob00005", "startTime": "2026-10-28T15:00:00-04:00",
     "endTime": "2026-10-28T15:30:00-04:00", "dateAdded": "2026-10-26T15:00:00.000Z", "appointmentStatus": "confirmed",
     "deleted": False, "title": "Discovery Call | Joey x Robin", "createdBy": {"source": "booking_widget"}},
    {"id": "eCas1", "calendarId": DISC, "contactId": "cCas00006", "startTime": "2026-11-09T10:00:00-05:00",
     "endTime": "2026-11-09T10:30:00-05:00", "dateAdded": "2026-11-06T14:25:00.000Z", "appointmentStatus": "cancelled",
     "deleted": False, "title": "Discovery Call | Joey x Casey", "createdBy": {"source": "booking_widget"}},
    {"id": "eCas2", "calendarId": DISC, "contactId": "cCas00006", "startTime": "2026-11-10T10:00:00-05:00",
     "endTime": "2026-11-10T10:30:00-05:00", "dateAdded": "2026-11-06T14:45:00.000Z", "appointmentStatus": "confirmed",
     "deleted": False, "title": "Discovery Call | Joey x Casey", "createdBy": {"source": "booking_widget"}},
    {"id": "eCasCopy", "calendarId": LSCAL, "contactId": "cCas00006", "startTime": "2026-11-10T10:10:00-05:00",
     "endTime": "2026-11-10T10:40:00-05:00", "dateAdded": "2026-11-06T14:46:00.000Z", "appointmentStatus": "confirmed",
     "deleted": False, "title": "Discovery Call | Joey x Casey", "createdBy": {"source": "google_calendar"}},
    {"id": "eTay", "calendarId": DISC, "contactId": "cTay00011", "startTime": "2026-11-02T10:00:00-06:00",
     "endTime": "2026-11-02T10:30:00-06:00", "dateAdded": "2026-10-29T14:05:00.000Z", "appointmentStatus": "noshow",
     "deleted": False, "title": "Discovery Call | Joey x Taylor", "createdBy": {"source": "mobile_app"}},
    {"id": "eOnb", "calendarId": DISC, "contactId": "cSam00002", "startTime": "2026-11-05T10:00:00-05:00",
     "endTime": "2026-11-05T10:30:00-05:00", "dateAdded": "2026-11-01T15:00:00.000Z", "appointmentStatus": "confirmed",
     "deleted": False, "title": "Onboarding Call | Joey x Sam", "createdBy": {"source": "mobile_app"}},
    {"id": "eOther", "calendarId": LSCAL, "contactId": "cPat00001", "startTime": "2026-10-23T10:00:00-04:00",
     "endTime": "2026-10-23T10:30:00-04:00", "dateAdded": "2026-10-21T15:00:00.000Z", "appointmentStatus": "confirmed",
     "deleted": False, "title": "Lead Suite coaching", "createdBy": {"source": "google_calendar"}},
]
NOTES = {
    "cSam00002": [{"id": "n1", "body": "<p>x</p>", "bodyText": (
        "OUTCOME: Talked 30 min. They have 12 beds and 3 open. Wants families from the hospital. Sent the plan. "
        "Next step is a follow up call Monday. Call her at 555-201-4477. Extra sentence seven."),
        "dateAdded": "2026-10-22T19:10:00.000Z", "contactId": "cSam00002"}],
    "cRob00005": [],
    "cCas00006": [],
    "cTay00011": [{"id": "n2", "body": "", "bodyText": "No show. Texted to rebook.", "dateAdded": "2026-11-02T17:00:00.000Z",
                   "contactId": "cTay00011"}],
}


def pipelines():
    stages = [{"id": ST[k], "name": n} for k, n in STAGE_NAMES.items()]
    return {"pipelines": [{"id": LS, "name": "Leadsuite Pipeline", "stages": stages},
                          {"id": "D26Fys9N44CiadqYjkm7", "name": "Email Pipeline", "stages": []}]}


def files():
    out = {
        "contacts.json": {"contacts": [], "total": 0},
        f"locations__{LOC}__customFields.json": {"customFields": [
            {"id": i, "name": n, "fieldKey": k, "dataType": "TEXT", "model": "contact"} for i, n, k in FIELDS]},
        "opportunities__pipelines.json": pipelines(),
        "opportunities__search.json": {"opportunities": OPPS, "meta": {"total": len(OPPS)}},
        "contacts__search.json": {"contacts": CONTACTS + [NOISE], "total": len(CONTACTS) + 1},
        "contacts__cTay00011.json": {"contact": TAYLOR},
        "conversations__search.json": {"conversations": [
            {"id": cv, "contactId": cid, "type": "TYPE_PHONE", "lastMessageDate": 1} for cid, (cv, _) in CONVS.items()]},
        "calendars__events.json": {"events": EVENTS},
    }
    for cid, (cv, msgs) in CONVS.items():
        newest_first = sorted(msgs, key=lambda m: m["dateAdded"], reverse=True)
        out[f"conversations__{cv}__messages.json"] = {"messages": {
            "lastMessageId": newest_first[-1]["id"] if newest_first else None, "nextPage": False,
            "messages": newest_first}}
    for cid, notes in NOTES.items():
        out[f"contacts__{cid}__notes.json"] = {"notes": notes}
    for mid, t in TRANSCRIPTS.items():
        out[f"conversations__locations__{LOC}__messages__{mid}__transcription.json"] = t
    return out


def write_fake_dir(path, drop=(), patch=None):
    os.makedirs(path, exist_ok=True)
    fs = files()
    if patch:
        patch(fs)
    for name, obj in fs.items():
        if name in drop:
            continue
        with open(os.path.join(path, name), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    return path


def profile():
    return {"key": "hq", "location": LOC, "pipeline": LS, "calendars": {"discovery": DISC, "lead_suite": LSCAL},
            "joey_contact": "ITgRAUyt3KqdPbQB5cUo", "artifact_url": "", "tag": "leadsuite"}
