# Client Desk

Your weekly client admin, done before you wake up. One page per client (AGC and Splendor) that has the owner's
Friday report, the Monday partner calls and open rooms email, and a "robocall or family?" answer for every unknown
caller. You check it and you send it. Nothing goes to a client, family or partner on its own.

## When it runs
7:00am Eastern, every Monday and Friday, once for AGC and once for Splendor. You can also ask any Claude session on
this repo for "client desk agc now" or "client desk splendor now".

## Where you see it
- **The desk page** for each client (links in `config/surven.json` under `artifacts.client_desk_agc` and
  `artifacts.client_desk_splendor`). It updates in place, so keep it pinned.
- **The report page** for each client, updated on Fridays (`artifacts.client_desk_agc_report` and
  `artifacts.client_desk_splendor_report`). This is the one you send to the owner.
- **One push notification** each run with the top line, like "Monday: 12 partners to call, 5 check-ins; open
  rooms email ready for 8; callers: 2 robocall, 1 unclear." (made-up example numbers)

## What is on the page

**Every run**
- The numbers: new families this week, how fast families heard from us, families toured so far, move-ins against
  the goal, partners on the weekly email list, messages waiting over 24 hours, unknown callers.
- **Unknown callers.** Every caller with no name that the planner is asking you about, shown as "Caller 1234" (last 4
  digits only). Each one has a verdict and the reason:
  - *Robocall likely*: nobody spoke when the call was answered, several new numbers from one area code in the same
    hour, a number almost the same as another unknown caller's, or a recorded message.
  - *Family likely*: they talked about a parent, a room, a tour or a price, or a hospital or social worker, or they
    texted back.
  - *Not a family*: they asked about a job, or it was a sales or listing call.
  - *Unclear*: not enough to tell. It says which way it leans and to listen to the recording (link included).
  There is a "Copy answers" button so you can answer the planner's NEED YOU questions in one go.
- **Waiting over 24 hours.** Anyone who wrote or called and got no answer from us since.

**Monday**
- **Partner calls**, oldest touch first, in four groups: not reached yet (To Call, No Answer), due the two-week
  check-in (Talked, Info Sent), on the weekly open rooms email list, and thank-you due (Sent a Referral). The weekly
  open rooms email does not count as a check-in or a thank-you; only a call, a text or a one-to-one email does. Each
  partner shows the place, the P code (text it to bridge the call), the type, the last touch and one line of what
  the planner knows. Each group has bullets of what to ask. You say it in your own words.
- **The open rooms email**, built like the one you already send ("Private and shared rooms this week"). Fill the two
  `[N]` blanks after the owner tells you which rooms are open, then send it from GoHighLevel. The first name and the
  phone fill in by themselves. It also lists partners with no email on file (call them first). There is a one-line
  text to the owner asking which rooms are open.

**Friday**
- **The owner report**: what came in, how fast families were reached, tours, move-ins against the goal, the partner
  program, what Surven did this week (calls, texts and emails sent), and next week's plan. Plain words, real counts.
  A zero means none; nothing is estimated. Calls GoHighLevel cancelled before they rang are not counted. Open the
  report page, check it, then send the client a screenshot of it, or
  copy the short text into a text or email. Never send the desk link itself to a client: it lists partners and
  callers.

Every word the owner or a partner could see has passed the copy checker first. If something breaks one of your copy
rules, the page says it is held and does not show it.

## What you do with it
1. Monday: answer the unknown callers in the planner using the verdicts. Text the owner for open rooms. Fill the
   blanks and send the open rooms email. Work the partner list top down.
2. Friday: read the report, fix anything you know is wrong, and send it to the owner.

## Time it saves
About 2 hours and 15 minutes a week across both clients: about 45 minutes building the AGC Friday report and 30 for Splendor, 15
for the open rooms email, 20 for working out which partners to call, and about 25 for the robocall-or-family
questions.

## Pause it
In claude.ai, open Routines, find "Client Desk: AGC" or "Client Desk: Splendor" and switch it off. Or ask Claude:
"pause the Client Desk routines".

## For builders
- Code: `pull.py` (read-only GoHighLevel pull; no phone numbers or emails kept, even in /tmp), `metrics.py` (who is
  a family, partner, staff or unknown caller, and every count), `triage.py`, `partners.py`, `email_draft.py`,
  `report.py`, `checks.py` (copy checker), `render.py` (both pages), `run.py` (runs it all). Settings:
  `clients.json`.
- Families follow the AGC collector's rule (`morning-sales-brief/occupancy_os/collectors/agc.py`) minus referral
  partners and internal or test records. `proposals/agc-collector-referral-partner.patch` is the same fix for the
  collector itself (a proposal; it is not applied there).
- Runbook: `.claude/skills/client_desk/SKILL.md`. Routines: `routines/client_desk.md`.
- Tests (offline, synthetic data): `python3 -m unittest discover -s tools/client_desk/tests -t .`
- Read-only test run (publishes nothing): `python3 -m tools.client_desk.run --client agc --mode friday --dry-run`
