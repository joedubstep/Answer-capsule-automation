# Inbox Desk (routine)

- **Name:** Inbox Desk
- **Class:** B (needs connectors): **Gmail**, **Notion**, **Google Drive**. The routine is created DISABLED. Joey
  attaches the three connectors in claude.ai under Routines and switches it on. Until then it also works on demand
  in any Claude session that has the connectors ("inbox desk now", "inbox desk backlog", "inbox desk dry run").
- **Environment:** Surven HQ (`surven_hq` in `config/surven.json`, `env_01LcNf8JTtUumgjrBBnvJ7pK`). It must be this
  one: only its key reads the Surven HQ GoHighLevel location, which gives each cold reply its E code and stage and
  finds opt-outs that still need a cleanup. In any other environment the desk still runs, without that context.
- **Schedule:** 8:00am and 4:00pm Eastern, Monday to Friday.
  - cron (UTC, twin-fired): `0 12,13,20,21 * * 1-5`
  - guard: `python3 -m tools.inbox_desk.desk guard` prints RUN only when the Eastern hour is 8 or 16.
- **Output:** Gmail drafts in each reply's thread, Learnings rows in Notion, plan PDFs (attached to drafts, copy in
  Drive), the Desk/Done label, and at most one digest email to Joey per run.
- **Cost:** each run reads only what is new (usually 3 to 10 threads after the first day). Python sorts, counts
  and checks; the model writes a few short drafts. About $0.15 to $0.50 per run on Sonnet, 10 runs a week.

## How one prompt covers 8am and 4pm all year
The cron fires four times a weekday, at 12, 13, 20 and 21 UTC. Eastern time is UTC-4 in summer and UTC-5 in winter:

| UTC fire | Summer (EDT) | Winter (EST) |
|---|---|---|
| 12:00 | 8am: RUN | 7am: SKIP |
| 13:00 | 9am: SKIP | 8am: RUN |
| 20:00 | 4pm: RUN | 3pm: SKIP |
| 21:00 | 5pm: SKIP | 4pm: RUN |

`desk guard` checks the Eastern hour of THIS fire against both 8 and 16, so exactly two of the four fires run, the
same prompt handles the morning and the afternoon, and nothing changes when the clocks change.

## Prompt

```
You run Inbox Desk for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m tools.inbox_desk.desk guard   -> if it prints SKIP, stop. Final message: "Inbox Desk: not this fire."
   (Skip this step if any message in this conversation says "Run now", in a payload block or as a plain message: that is a manual run.)
2b. Load the connector tools with ToolSearch: the Gmail tools (search threads, get thread, list labels, create label,
   label thread, list drafts, create draft, send message) and the Notion tools (fetch, create pages). Google Drive
   (create file) is optional. If the Gmail or Notion tools are missing, stop. Final message:
   "Inbox Desk: needs connectors Gmail, Notion, Google Drive, add them in claude.ai Routines."
3. Read .claude/skills/inbox_desk/SKILL.md and follow it in scheduled mode. Run every command from /home/user/aca.
Hard rules: never message anyone but Joey (the one digest email to his own Gmail); drafts only, never send a draft;
GHL is read-only; never print or look for keys; never write names, emails or message text into the repo.
Final message: one line, as the skill says.
```

## Before the first scheduled run (deploy step)
1. Add to `config/surven.json`:
   `"inbox_desk": {"booking_link": "https://start.surven.ai/booking-page-6259"}` (the booking link from Joey's live
   price-raise emails; until it is set, every draft that needs it is held and the digest says so) and
   `"notion": {..., "inbox_desk_settings": "<page id>"}` (step 3).
2. Notion: the Learnings data source (`notion.learnings_ds`) and the Answer Bank page (`notion.answer_bank`) already
   exist. Check the Learnings schema still reads: Title (title), Source (text), Date (date), Summary (text),
   Key lines (text), Apply to (multi-select: JP delivery, Offer, Sales calls, Campaigns, Ads, Ops), Link (url),
   Applied (checkbox).
3. Notion: create a private page "Inbox Desk settings" under Automations (`notion.automations_home`) with one line
   per person who writes from a personal address, in this form, and put its id in config:
   `client legacy: <the legacy client's address>`, `coach <name>: <address>` (every coach who writes from a
   personal Gmail), `own: <Joey's other inboxes>`,
   `ignore: <address>`. Never put these addresses in the repo.
4. Run "inbox desk dry run" once in a Surven HQ session with the connectors. Check the counts look right.
5. Run "inbox desk backlog" once on demand (drafts only). It drafts answers to the cold replies since 9/23 that
   nobody answered, including the homes that asked for the plan.
6. Create the routine above (environment Surven HQ, cron `0 12,13,20,21 * * 1-5`), DISABLED. Joey attaches Gmail,
   Notion and Google Drive in claude.ai Routines and switches it on.
7. Joey, once, in Gmail: Settings, Accounts, "Send mail as", add each joey@ address of the cold email domains
   (`cold_email_domains` in config; the SMTP server is the ImprovMX one the cold email engine sends with). The
   Gmail connector cannot pick a From address, so a draft opens with the default one. With the aliases added,
   Joey picks the address the home wrote to before he presses Send. Without them, the reply goes out from his
   own Gmail address.

## Pause it
In claude.ai, open Routines, find "Inbox Desk" and switch it off. Or ask Claude: "pause the Inbox Desk routine".
