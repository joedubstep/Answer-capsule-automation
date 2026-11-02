---
name: time_ledger
description: Time Ledger files Joey's 15-minute log. Each night it reads the "15 min log" sections at the bottom of Joey's To-Do page in Notion, labels every action (role, task, kind, AI), estimates minutes from the block times, suggests rows for blank blocks from Google Calendar, Gmail, Fathom and Surven HQ GoHighLevel calls (marked inferred), and adds only the new rows to the 15-Min Action Log database. On Sundays it also writes a weekly time report page in Notion and emails it to Joey. Use it on the 11:45pm ET schedule, or on demand ("run the time ledger", "backfill the time ledger", "weekly time report", or add "dry run").
---

# Time Ledger

## Purpose
Keep Joey's 15-minute log useful without him maintaining it: one clean row per action in Notion, honest minute
estimates, blank blocks filled from evidence, and one weekly report that says where the time went. Python
parses, labels, counts and dedupes; you fetch, judge the unsure labels, gather evidence and write.

## Modes
- **nightly** (scheduled 11:45pm ET every day, or "run the time ledger"): steps 0 to 9 for the log day (before
  4am ET still counts as the day before), the day before, and any day up to 3 days back that the copied log
  sections hold. On Sundays, steps 10 to 13 follow.
- **weekly** ("weekly time report"): steps 0 to 9, then 10 to 13 even if it is not Sunday. On a weekday it reports
  the last full Monday to Sunday week.
- **backfill** ("backfill the time ledger"): steps 0 to 9 with `--mode backfill`: every day on the page. Gather
  evidence for at most the 5 most recent days in the evidence plan.
- **dry run** (add "dry run"): every step except the Notion writes (steps 8 and 12) and the email (step 13).
  Run `finish --dry-run` and `weekly --dry-run` and say what would have been written. Reading is fine.

## Inputs
- `config/surven.json`: `notion.joey_todo_page_15min_log` (the To-Do page), `notion.action_log_ds` (the
  15-Min Action Log data source), `notion.automations_home` (where weekly pages go), `google.joey_gmail` (the
  only address the report may be emailed to), `google.surven_calendar` (checked for blank blocks next to the
  primary calendar).
- Connectors: Notion (required), Google Calendar and Gmail (blank-block evidence; Gmail also sends the Sunday
  email), Fathom (optional evidence).
- Surven HQ GoHighLevel calls through `shared/ghl.py` when this runs in the Surven HQ environment (read-only;
  elsewhere Python says it is unavailable and carries on).
- `tools/time_ledger/model.json`: the trained labeler (no action text inside).

## Steps
Run every command from the repo root. Work files live in `/tmp/time_ledger/` only. Never open
`page_rows.json`, `rows_window.json`, `new_rows.json` or `write_rows.json` yourself (they are big); Python reads
them.

0. **Setup.** `rm -rf /tmp/time_ledger && mkdir -p /tmp/time_ledger`. With ToolSearch, load the Notion tools
   `notion-fetch`, `notion-query-data-sources`, `notion-create-pages`, the Google Calendar tool `list_events`, the
   Gmail tools `search_threads` and `send_message`, and the Fathom tool `list_meetings`. No Notion tools: stop,
   final message `Time Ledger: needs connectors Notion, add them in claude.ai Routines.` Missing Calendar or
   Gmail: carry on without that evidence (and without the email on Sundays) and say so in the final message.
1. **The log.** Notion fetch with `id` = `notion.joey_todo_page_15min_log`. Note its `page_last_edited_at`.
   - If the tool result was saved to a file, copy that file to `/tmp/time_ledger/page.md`.
   - Otherwise write `/tmp/time_ledger/page.md` with the page content from the first heading line that contains
     `15 min log` (a `## ` line or an `<h2>` block) down to just before the 5th such heading (backfill: to the
     end). Copy those lines exactly, character for character: times, slashes, typos and all. You may leave out
     lines that are only `<p />`. Never fix, reword or reorder anything; the row keys depend on the exact text.
   - Never edit the To-Do page.
2. **What to compare.**
   `python3 -m tools.time_ledger.run sql --mode nightly --page /tmp/time_ledger/page.md --edited <page_last_edited_at>`
   (`--mode backfill` in backfill). It prints `LOG DAY`, `WEEKLY REPORT DUE`, `DATA SOURCE` and one `SQL` line.
3. **What is already logged.** Notion query data sources with exactly
   `{"data": {"data_source_urls": ["<DATA SOURCE>"], "query": "<SQL>"}}`. Write the tool's JSON result (the
   object with `results`) to `/tmp/time_ledger/existing.json`. If `has_more` is true, run it again with
   ` OFFSET 1000` added at the end of the SQL and merge the `results` lists.
4. **Parse, label, dedupe.**
   `python3 -m tools.time_ledger.run prepare --page /tmp/time_ledger/page.md --existing /tmp/time_ledger/existing.json --mode nightly --edited <page_last_edited_at>`
   (`--mode backfill` in backfill).
   - `NO LOG FOUND`: go to step 9.
   - `DATE CHECK` lines: a heading whose date repeats or is out of order, or a section that runs into a new
     morning. Python already dated those rows (for example the top duplicate "15 min log 11/1" read as the page's
     last-edit day). Mention each one in the final message in a few words so Joey can fix the heading. Never edit
     the page yourself.
   - `NOTHING NEW`: go to step 9.
5. **Label the unsure rows (your judgment).** Read `/tmp/time_ledger/needs_label.json`: each row has `key`,
   `text`, `same_block` (the actions next to it), the classifier's `guess` and `top3`. Write
   `/tmp/time_ledger/labels.json` as `{"<key>": {"role": "...", "task": "...", "kind": "...", "ai": true|false}}`
   for every row in it (keep the guess when it is right). Allowed values:
   - **role**: CEO (direction, planning, coach calls, learning), Sales (sales calls, cold calls, outreach and
     follow-ups with owners), Offer work (guarantee, value enhancers, bonuses, metaphors, pricing), Marketing
     (Surven's own brand, profiles, ads, VSL), Client delivery (client builds in Meta and GHL, client calls,
     posts, client agents and SOPs), CTO (Claude, prompts, skills, tokens, Wi-Fi and tool setup for Surven
     itself), Business development (side deals like selling logs and code), Admin (email, calendar, phone
     settings, texts, spam calls), Billing and finance (bank, invoices, payments), HR and hiring (finding, hiring
     and training people), Personal (anything not work).
   - **kind**: Outreach, Selling, Client work, Offer, Learning, Personal, Distraction, Tools, Planning,
     Data sale, Marketing, Admin, SOPs, Fixes, Other.
   - **task**: one of Other, Claude and tool upkeep, Checking Claude's builds, Offer and guarantee,
     Admin (email, bank, phone), Distractions and personal, Client calls and posts, Client builds (Meta, GHL),
     Client follow-up agent, Data sale, Outreach and marketing, Calls (other), Planning, Learning and coaching,
     SOP writing, Fixes.
   - The role is the business purpose, not the tool: a prompt to fix a client's agent is Client delivery with
     `ai` true; a prompt to fix Claude's own setup is CTO. Phone apps (reels, dating apps, Snapchat) are Personal
     with kind Distraction. `ai` is true when the action is done with or about Claude or another AI tool.
6. **Blank blocks (only if `prepare` printed `BLANK WINDOWS` above 0).** Read
   `/tmp/time_ledger/evidence_plan.json`: one entry per day with its blank `windows` and the exact lookups.
   At most 3 days (5 in backfill), newest first. For each day:
   - Calendar `list_events` once per id in `calendar.calendarIds`: `calendarId` = that id (leave it out for
     `primary`), `startTime`, `endTime` and `orderBy` from the plan, `pageSize` 25.
   - Gmail `search_threads` with `query` = `gmail_query`, `view` `THREAD_VIEW_SUMMARY`, `pageSize` 25. Keep only
     messages whose `sender` is Joey's own address (`google.joey_gmail`). The result has no send time; Python reads it from the
     message `id`.
   - Fathom `list_meetings` with the plan's `created_after` and `created_before`, `max_pages` 1.
   Write one JSON list to `/tmp/time_ledger/evidence.json` with only these fields:
   `{"source": "calendar", "start": "<start.dateTime>", "end": "<end.dateTime>", "title": "<summary>", "attendees": <number of attendees other than Joey>, "recurring": <true if it has recurringEventId>}`
   (skip events with `status` cancelled, all-day events and events Joey declined),
   `{"source": "gmail", "id": "<message id>", "title": "<subject>"}`,
   `{"source": "fathom", "date": "YYYY-MM-DD", "title": "<title>"}`.
   Never copy email bodies, snippets, addresses or phone numbers. Python decides what overlaps which window.
7. **Build the rows.**
   `python3 -m tools.time_ledger.run build --labels /tmp/time_ledger/labels.json --evidence /tmp/time_ledger/evidence.json --ghl`
   (leave out `--labels` or `--evidence` when you did not write that file). It prints `TO WRITE: N` and one
   `BATCH:` file per 50 rows. `GHL: ... unavailable` is fine outside the Surven HQ environment.
8. **Write the rows (not in dry run).** For each `BATCH:` file in order: Notion create pages with `parent` =
   the file's `parent`, `pages` = the file's `pages`, exactly as written (do not change any value), and
   `allow_async` false. Count the rows created. If a call fails, try it once more; if it fails again, stop
   writing and say so.
9. **Finish.** `python3 -m tools.time_ledger.run finish --written <rows created> --ghl`
   (dry run: `finish --dry-run --ghl`). It prints the one-line daily summary for the final message.

**Weekly report** (when step 2 printed `WEEKLY REPORT DUE: yes`, or in weekly mode):

10. `python3 -m tools.time_ledger.run weekly-sql` (weekly mode on a weekday: same command; it picks the last full
    week). Run `SQL A` and `SQL B` with Notion query data sources on the same data source, the same way as step 3.
    Save the JSON results to `/tmp/time_ledger/week_this.json` and `/tmp/time_ledger/week_prev.json` (merge pages
    if `has_more`).
11. `python3 -m tools.time_ledger.run weekly --this /tmp/time_ledger/week_this.json --prev /tmp/time_ledger/week_prev.json`
    (dry run: add `--dry-run`; if the database is still empty, use `--from-page` instead, which reads this run's
    parse). It prints `WEEKLY READY: <title>`, a `HEADLINE` and the two files below. `EMAIL BLOCKED` means the
    config address is wrong: write the Notion page, send no email, and say so.
12. **Notion page (not in dry run).** From `/tmp/time_ledger/notion_page.json`: Notion create pages with that
    `parent` (a page id: the Automations page) and the one page in `pages` (title, icon, content exactly).
    Note the new page's URL.
13. **Email Joey (not in dry run).** From `/tmp/time_ledger/email.json`: Gmail `send_message` with `to` exactly as
    in the file, `subject`, `body` and `htmlBody`. Put one first line in `body`: `Full report in Notion: <page URL>`.
    The only allowed recipient is Joey's own address (`google.joey_gmail`; Python checks it before it writes the
    file): if `to` is empty, holds anything else, or more than one address, do not send and say so. Never cc or
    bcc anyone.

## What lands where
- **15-Min Action Log** (Notion database `notion.action_log_ds`): one row per new action with Action, Date,
  Block start, Minutes (est), Role, Task, Kind, AI, Confidence, Source (log or inferred) and Key. Breaks are rows
  with Role "Not logged" and Task "Break"; a blank block with no evidence is one "(blank block)" row; a blank
  block with evidence gets inferred rows instead.
- **Sundays:** one Notion page "Time Ledger: week of <Mon> to <Sun>" under Automations, and the same report
  emailed to Joey (HTML with a plain-text copy).
- Working files only in `/tmp/time_ledger/`. The To-Do page is never edited. Nothing is written to this repo.

## Hard rules
- Read-only on the To-Do page. Never edit, move or archive log text.
- Never message anyone but Joey. The weekly email goes only to his own address (`google.joey_gmail`).
- GoHighLevel is read-only. Never print, echo or look for an API key.
- No personal data in the repo; action text, names and email subjects stay in Notion, Gmail and `/tmp`.
- Keep it cheap: Python parses, labels, counts and dedupes. You only fetch, copy, label the rows in
  `needs_label.json`, gather evidence for the planned windows, and write what Python prepared. Never dump the
  whole database or inbox; never open the big work files.
- Every minute is an estimate; never present one as exact.

## Final message format
One line: the line `finish` printed, then any of: `Date fix: <heading> read as <date>.`, `Weekly report: <Notion
URL>, emailed to you.`, `No evidence lookups: <connector> missing.`, `Write failed after <n> rows.` Examples:
`Time Ledger Nov 2: 13 actions, about 2.2 h of work; Sales 60 min, Personal 30 min, Client delivery 21 min; selling 60 min; distraction 21 min (0 day(s) under 20 min in a row); 1 blank block(s), 0 filled from your calendar or email; 27 new row(s) in the Action Log. Date fix: top "15 min log 11/1" read as Nov 2.`
`Time Ledger Nov 8: ... 31 new row(s) in the Action Log. Weekly report: https://app.notion.com/p/..., emailed to you.`
