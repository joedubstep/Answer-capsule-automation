# Time Ledger (routine)

- **Name:** Time Ledger
- **Class:** B (needs connectors). The routine is created **disabled**. Joey attaches the connectors in claude.ai
  under Routines and switches it on. The skill also works on demand in any Claude session that has the
  connectors: open a session on this repo and say "run the time ledger", "backfill the time ledger",
  "weekly time report", or add "dry run".
- **Connectors:** Notion (required), Google Calendar and Gmail (blank-block evidence, and Gmail sends the Sunday
  email). Fathom is optional extra evidence if it is attached too.
- **Environment:** Surven HQ (`surven_hq` in `config/surven.json`, `env_01LcNf8JTtUumgjrBBnvJ7pK`). Its key reads the
  Surven HQ GoHighLevel calls, so a blank block during a dialing session gets "Made 12 calls, 2 answered" and the
  daily line shows dials and talk minutes. In any other environment it still runs, without the call data.
- **Schedule:** 11:45pm Eastern, every day. On Sundays the same run also writes the weekly report.
  - cron (UTC, twin-fired): `45 3,4 * * *`
  - guard hour: `23` (`python3 -m shared.et guard 23` lets exactly one of the two fires run, summer and winter:
    03:45 UTC is 11:45pm in summer, 04:45 UTC is 11:45pm in winter)
- **Skill:** `.claude/skills/time_ledger/SKILL.md`. Code: `tools/time_ledger/`.
- **Output:** new rows in the Notion 15-Min Action Log every night; on Sundays a "Time Ledger: week of ..." page
  under Automations in Notion and the same report emailed to Joey's own Gmail (`google.joey_gmail`, the only
  recipient).
- **Cost:** about $0.10 to $0.30 a night on Sonnet. One page fetch (only the top four log sections are copied),
  one SQL read of the keys for the days those sections hold (2 to 4 days), about 15 to 25 short labels, a calendar
  and Gmail lookup only when a block is blank, and one Notion write of about 20 to 40 rows. A night with nothing
  new stops after the parse. Sundays add two SQL reads (one week of rows), one Notion page and one email.

## Prompt

```
You run Time Ledger for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m shared.et guard 23   -> if it prints SKIP, stop. Final message: "Time Ledger: not this fire."
   (Skip this step if the conversation has a routine-fire-payload block saying exactly "Run now".)
2b. Check with ToolSearch that the Notion connector tools exist (notion-fetch, notion-create-pages,
   notion-query-data-sources). If they are missing, stop. Final message: "Time Ledger: needs connectors Notion,
   Google Calendar, Gmail, add them in claude.ai Routines." If only Google Calendar or Gmail is missing, carry on;
   the skill says what to skip.
3. Read .claude/skills/time_ledger/SKILL.md and follow it in nightly mode (it adds the weekly report on Sundays).
   Run every command from /home/user/aca.
Hard rules: never message anyone but Joey; the only email goes to Joey's own Gmail (config google.joey_gmail); never edit the To-Do
page; GHL is read-only; never print or look for keys.
Final message: one line, as the skill says.
```

## Before the first scheduled run (deploy step)
1. The Notion database already exists: "15-Min Action Log" under SURVEN HQ / Automations
   (`notion.action_log_db` and `notion.action_log_ds` in `config/surven.json`). Its schema was checked read-only
   on 2026-11-02 and matches: Action (title), Date (date), Block start (text), Minutes (est) (number), Role
   (select: the 11 roles plus "Not logged"), Task (text), Kind (select: the 15 kinds plus "Not logged"), AI
   (checkbox), Confidence (number), Source (select: log, inferred), Key (text). No new database is needed. It was
   still empty on 2026-11-02.
2. Create the routine above in the Surven HQ environment, **disabled**, with the cron, guard and prompt.
3. Joey attaches Notion, Google Calendar and Gmail (Fathom optional) to the routine, then switches it on.
4. Run the backlog once on demand in a session with the connectors: "backfill the time ledger". That writes every
   day on the page (about 320 rows from Oct 24 on, about 130 of them labeled by Claude) so the first Sunday report has a week to compare with.
5. Optional: "time ledger dry run" first to see what it would write.

## Pause it
In claude.ai, open Routines, find "Time Ledger" and switch it off. Or ask Claude: "pause the Time Ledger routine".
