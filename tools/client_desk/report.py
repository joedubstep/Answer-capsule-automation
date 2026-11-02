"""Friday owner report: what came in, how fast families were reached, tours, move-ins against the goal, the partner
program, what Surven did, and next week's plan. Plain words, real counts only: zero is zero and no number is
invented. Two forms come from the same sentences: the page (render.render_report) and a short text for a text
message or email. Every line passes the copy checker as client text before it reaches the page.
"""
import datetime as dt

from tools.client_desk import checks
from tools.client_desk import metrics as M


def plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def within(minutes):
    """'in under a minute' or 'within 4 minutes'."""
    d = duration(minutes)
    return ("in " + d) if d == "under a minute" else ("within " + d)


def duration(minutes):
    if minutes is None:
        return ""
    m = float(minutes)
    if m < 1:
        return "under a minute"
    if m < 60:
        return plural(int(round(m)), "minute")
    if m < 60 * 24:
        h, mm = int(m // 60), int(round(m % 60))
        return plural(h, "hour") + (" " + plural(mm, "minute") if mm else "")
    return plural(int(round(m / 1440.0)), "day")


def day_label(iso):
    t = M.ts(iso)
    if not t:
        return ""
    t = M.et.to_et(t)
    return t.strftime("%b ") + str(t.day)


def period(desk):
    end = M.ts(desk["week"]["end"]) - dt.timedelta(minutes=1)
    return "%s to %s" % (day_label(desk["week"]["start"]), day_label(end.isoformat()))


WAYS = {"website": "the website", "website chat": "the website chat", "phone call": "a phone call", "text": "a text",
        "email": "an email", "referral partner": "a referral partner", "other": "another way"}


def build(desk, call_counts=None, note=None, triage_items=None):
    f, t, mi, g = desk["families"], desk["tours"], desk["move_ins"], desk["goal"]
    pa, act = desk.get("partners"), desk["activity"]
    home = desk["label"]
    sections = []

    # what came in
    lines = []
    if f["new_week"] == 0:
        lines.append("No new families came in this week.")
    else:
        lines.append("%s came in this week." % plural(f["new_week"], "new family", "new families"))
        for k, n in sorted(f["new_by_way"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append("%d came from %s." % (n, WAYS.get(k, k)))
    if f["unknown_callers_week"]:
        # the same people both numbers count: unknown callers whose record was added this week
        start, end = M.ts(desk["week"]["start"]), M.ts(desk["week"]["end"])
        week_callers = [i for i in triage_items or [] if M.inside(i.get("added"), start, end)]
        robo = sum(1 for i in week_callers if i["verdict"] == "robocall-likely")
        lines.append("%s with no name called or texted." % plural(f["unknown_callers_week"], "new number"))
        if robo:
            lines.append(("1 looks like a robocall." if robo == 1 else "%d look like robocalls." % robo)
                         + " We check each one.")
        else:
            lines.append("We check each one to see if it is a family.")
    sections.append({"key": "came_in", "title": "What came in",
                     "stats": [("New families this week", f["new_week"]), ("Families so far", f["total"])],
                     "lines": lines})

    # speed
    lines = []
    if f["speed_week_n"] == 1:
        lines.append("1 new family heard from us this week, %s." % within(f["speed_week_min"]))
    elif f["speed_week_n"]:
        lines.append("%d new families heard from us this week. Half of them heard from us %s." % (
            f["speed_week_n"], within(f["speed_week_min"])))
    elif f["new_week"]:
        lines.append("No first call or text to this week's new families is on record yet.")
    else:
        lines.append("With no new families this week, there is no speed to report.")
    if f.get("new_no_touch") and f["speed_week_n"]:
        lines.append("%s no call or text from us on record yet." % plural(f["new_no_touch"], "new family has",
                                                                          "new families have"))
    if f["speed_month_n"] and f["speed_month_n"] != f["speed_week_n"]:
        if f["speed_month_n"] == 1:
            lines.append("Over the last 30 days, 1 new family heard from us, %s." % within(f["speed_month_min"]))
        else:
            lines.append("Over the last 30 days, %d new families heard from us. Half of them heard from us %s." % (
                f["speed_month_n"], within(f["speed_month_min"])))
    lines.append("We talked with %s this week." % plural(f["reached_week"], "family", "families"))
    stats = [("Families we talked with", f["reached_week"])]
    if f["speed_week_n"]:
        stats.insert(0, ("Time to first call or text", duration(f["speed_week_min"])))
    sections.append({"key": "speed", "title": "How fast families were reached", "stats": stats, "lines": lines})

    # tours
    lines = []
    if t["held_week"]:
        lines.append("%s happened this week." % plural(t["held_week"], "tour"))
    else:
        lines.append("No tours happened this week.")
    if t["upcoming"]:
        lines.append("%s on the calendar for the next 7 days." % plural(t["upcoming"], "tour is", "tours are"))
    lines.append("%s toured so far." % plural(t["toured_to_date"], "family has", "families have"))
    sections.append({"key": "tours", "title": "Tours",
                     "stats": [("Tours booked this week", t["booked_week"]), ("Tours this week", t["held_week"]),
                               ("Families toured so far", t["toured_to_date"])],
                     "lines": lines})

    # move-ins vs goal
    lines, stats = [], [("Move-ins so far", mi["to_date"])]
    by = day_label(g["by"]) if g.get("by") else ""
    if g.get("move_ins"):
        stats.append(("Move-in goal", "%d by %s" % (g["move_ins"], by)))
        lines.append("%d of %d move-ins so far." % (mi["to_date"], g["move_ins"]))
    if g.get("tours"):
        stats.append(("Tour goal", "%d by %s" % (g["tours"], by)))
        lines.append("%d of %d tours so far." % (t["toured_to_date"], g["tours"]))
    if mi["week"]:
        lines.append("%s this week." % plural(mi["week"], "family moved in", "families moved in"))
    if g.get("days_left") is not None and by:
        if g["days_left"] >= 0:
            lines.append("The goal date is %s, %s away." % (by, plural(g["days_left"], "day")))
        else:
            lines.append("The goal date was %s." % by)
    if not (g.get("move_ins") or g.get("tours")):
        lines.append("No goal is set yet.")
    sections.append({"key": "goal", "title": "Move-ins and the goal", "stats": stats, "lines": lines})

    # partners
    if pa:
        lines = []
        stage_list = ["%s: %d" % (r["name"], r["total"]) for r in pa["stages"] if r["total"]]
        mv = pa["moves"]
        if mv["moved"]:
            lines.append("%s moved to a new stage this week." % plural(mv["moved"], "partner"))
        else:
            lines.append("No partner moved to a new stage this week.")
        lines.append("We called, texted or emailed %s this week." % plural(pa["touches"]["partners_touched"], "partner"))
        goal = pa.get("goal") or {}
        if goal.get("yes_partners") or goal.get("referrals"):
            lines.append("The target was %d partners on the weekly email and %d referrals by %s. Now: %d and %d." % (
                goal.get("yes_partners") or 0, goal.get("referrals") or 0, day_label(goal.get("by")),
                pa["on_weekly_list"], pa["sent_referral"]))
        sections.append({"key": "partners", "title": "Referral partners",
                         "stats": [("Partners on the list", pa["total"]),
                                   ("On the weekly email list", pa["on_weekly_list"]),
                                   ("Sent a referral", pa["sent_referral"])],
                         "lines": lines, "list_title": "Where the %s stand" % plural(pa["total"], "partner"), "list": stage_list})

    # what Surven did
    lines = ["We made %s, sent %s and %s for the home this week." % (
        plural(act["calls"], "call"), plural(act["texts"], "text"), plural(act["emails"], "email"))]
    if act["calls_answered"]:
        lines.append("We answered %s from families and partners." % plural(act["calls_answered"], "call"))
    sections.append({"key": "did", "title": "What we did this week",
                     "stats": [("Calls", act["calls"]), ("Texts", act["texts"]), ("Emails", act["emails"])],
                     "lines": lines})

    # next week
    plan = next_week(desk, call_counts or {})
    sections.append({"key": "next", "title": "Next week", "stats": [], "lines": [], "bullets": plan})
    if note:
        sections.append({"key": "note", "title": "A note from Joey", "stats": [], "lines": [note]})

    title = "%s weekly report" % home
    rep = {"title": title, "home": home, "period": period(desk), "sections": sections,
           "text": short_text(desk, plan)}
    rep["check"] = {"page": checks.check(plain_text(rep), "client"), "text": checks.check(rep["text"], "client")}
    return rep


def next_week(desk, call_counts):
    pa, t = desk.get("partners"), desk["tours"]
    out = []
    if pa:
        if call_counts.get("first_calls"):
            out.append("Call the %s we have not reached yet." % plural(call_counts["first_calls"], "partner"))
        if call_counts.get("check_ins"):
            out.append("Check in with %s we last spoke with two or more weeks ago." % plural(call_counts["check_ins"], "partner"))
        n = call_counts.get("email_recipients", pa["on_weekly_list"])
        if n:
            out.append("Send the open rooms email to %s on Monday." % plural(n, "partner"))
    if desk.get("deciding"):
        out.append("Follow up with the %s." % plural(desk["deciding"], "family who toured or is deciding",
                                                     "families who toured or are deciding"))
    if t["upcoming"]:
        out.append("Get ready for %s on the calendar." % plural(t["upcoming"], "tour"))
    out.append("Call every new family the same day they reach out.")
    return out


def short_text(desk, plan):
    f, t, mi, g, act, pa = desk["families"], desk["tours"], desk["move_ins"], desk["goal"], desk["activity"], desk.get("partners")
    lines = ["%s this week (%s):" % (desk["label"], period(desk)),
             "New families: %d" % f["new_week"],
             "Families we talked with: %d" % f["reached_week"],
             "Tours: %d this week, %d so far" % (t["held_week"], t["toured_to_date"])]
    if g.get("move_ins"):
        lines.append("Move-ins: %d of %d (goal date %s)" % (mi["to_date"], g["move_ins"], day_label(g["by"])))
    else:
        lines.append("Move-ins: %d" % mi["to_date"])
        if g.get("tours"):
            lines.append("Tour goal: %d of %d by %s" % (t["toured_to_date"], g["tours"], day_label(g["by"])))
    if pa:
        lines.append("Partners: %d on the weekly email list, %d sent a referral" % (pa["on_weekly_list"], pa["sent_referral"]))
    lines.append("We made %s, sent %s and %s." % (plural(act["calls"], "call"), plural(act["texts"], "text"),
                                                   plural(act["emails"], "email")))
    if plan:
        lines.append("Next week: " + plan[0][0].lower() + plan[0][1:])
    return "\n".join(lines)


def plain_text(rep):
    out = [rep["title"], rep["period"]]
    for s in rep["sections"]:
        out.append(s["title"])
        for k, v in s.get("stats") or []:
            out.append("%s: %s" % (k, v))
        if s.get("list"):
            out.append(s.get("list_title") or "")
            out += [x + "." for x in s["list"]]
        out += s.get("lines") or []
        out += s.get("bullets") or []
    return "\n".join(out)


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
