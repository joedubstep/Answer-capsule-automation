"""Synthetic Gmail connector JSON for the Inbox Desk tests. Every name, home, address and number is made up."""
import json
import os

_CFG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "surven.json")
with open(_CFG, encoding="utf-8") as _f:
    _C = json.load(_f)

COLD_TO = "joey@" + _C["cold_email_domains"][0]   # a campaign mailbox (config/surven.json)
SHARED_TO = "joey@surven.ai"                         # Joey's main business domain, also a campaign domain
JOEY = _C["google"]["joey_gmail"]                    # read from config, never typed into a test


def msg(mid, sender, to, subject, body="", date="2026-11-02T13:00:00Z", labels=("INBOX", "CATEGORY_PERSONAL"),
        snippet=None, html=None):
    m = {"id": mid, "threadId": mid, "sender": sender, "toRecipients": [to] if isinstance(to, str) else list(to),
         "subject": subject, "date": date, "labelIds": list(labels),
         "snippet": snippet if snippet is not None else (body or "")[:120],
         "viewUrl": "https://mail.google.com/mail/#all/" + mid}
    if body:
        m["plaintextBody"] = body
    if html:
        m["htmlBody"] = html
    return m


def thread(tid, *messages):
    ms = []
    for i, m in enumerate(messages):
        m = dict(m)
        m["threadId"] = tid
        if i == 0:
            m["id"] = tid
        ms.append(m)
    return {"id": tid, "messageCount": len(ms), "messages": ms, "viewUrl": "https://mail.google.com/mail/#all/" + tid}


def gmail_quote(text, domain="getsurven.com", when="Wed, Oct 28, 2026 at 9:41 AM"):
    lines = "\n".join("> " + l for l in text.split("\n"))
    return f"\n\nOn {when} Surven Occupancy <joey@{domain}> wrote:\n\n{lines}\n>"


def outlook_quote(text, domain="survenhq.com"):
    return ("\n\n________________________________\n\nFrom: Surven Occupancy <joey@" + domain + ">\n"
            "Sent: Saturday, 31 October 2026 09:23:45\nTo: Pat Example <pat@examplehome.com>\n"
            "Subject: Re: Do you have an open room?\n\nBe Careful With This Message\n\n" + text)


ROOMS_Q = "Hi Pat, how many rooms are open at Maple Example House right now?\n\nJoey"
NUDGE = "Hey, I just emailed you.\n\nJoey"
PLAN_OFFER = ("Pat, one more idea. I'd be willing to write up a one-page plan for filling the 2 open rooms. "
              "No call needed. Want me to send it?\n\nJoey\n\n(Reply no and I'll stop emailing.)")
TOOL_OFFER = ("Hi Pat, I saw Maple Example House has Facebook ads running since early December 2025.\n\n"
              "If follow-up takes forever, I built a free tool for senior living that gets families to tour by itself."
              "\n\nReply \"yes\" and I'll let you give it a try.\n\nJoey")


def cold(tid, body, quote=ROOMS_Q, subject="Re: Do you have an open room?", sender="pat@examplehome.com",
         to=COLD_TO, style="gmail", date="2026-11-02T13:00:00Z", labels=("INBOX", "CATEGORY_PERSONAL")):
    domain = to.split("@")[1]
    q = "" if quote is None else (gmail_quote(quote, domain) if style == "gmail" else outlook_quote(quote, domain))
    return thread(tid, msg(tid, sender, to, subject, body + q, date=date, labels=labels))


GV_FOOTER = ("\nTo respond to this text message, reply to this email or visit Google Voice.\nYOUR ACCOUNT "
             "<https://voice.google.com> HELP CENTER\nThis email was sent to you because you indicated that you'd "
             "like to receive\nemail notifications for text messages.\nGoogle LLC\n")


def gv(tid, text, who="(555) 010-0199", own=False):
    subject = ("New text message from SplendorResidence (555) (555) 010-0100" if own
               else f"New text message from {who}")
    sender = "15550100000.15550100100.abcDEF@txt.voice.google.com"
    return thread(tid, msg(tid, sender, JOEY, subject, "<https://voice.google.com>\n" + text + GV_FOOTER,
                           labels=("INBOX", "CATEGORY_UPDATES")))


def search_result(*threads_):
    """search_threads (THREAD_VIEW_SUMMARY) shape: the latest message only, no body."""
    out = []
    for t in threads_:
        last = dict(t["messages"][-1])
        last.pop("plaintextBody", None)
        last.pop("htmlBody", None)
        out.append({"id": t["id"], "messageCount": t["messageCount"], "messages": [last]})
    return {"resultCountEstimate": str(len(out)), "threads": out}
