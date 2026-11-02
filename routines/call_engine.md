# Call Engine (two routines)

- **Class:** B (needs connectors). Both routines are created **disabled**. Joey attaches the connectors in
  claude.ai under Routines and switches them on. The skill also works on demand in any Claude session that
  has the connectors: open a session on this repo and say "prep my calls", "review <fathom link>",
  "backfill since 2026-10-01", or add "dry run".
- **Connectors:** Fathom, Notion, Google Calendar, Gmail. (Review does not use Calendar; attaching it to both
  is fine.)
- **Environment:** Surven HQ (`surven_hq` in `config/surven.json`, `env_01LcNf8JTtUumgjrBBnvJ7pK`). It must
  be this one: only its key reads the HQ GoHighLevel calendars and contacts (prep needs them, because
  discovery calls booked in GHL show on Google only as hidden busy blocks) and only it can text Joey.
- **Skill:** `.claude/skills/call_engine/SKILL.md`. Code: `tools/call_engine/`.

## Routine 1: Call Engine Prep
- **Schedule:** 6:30am Eastern, Monday to Friday.
  - cron (UTC, twin-fired): `30 10,11 * * 1-5`
  - guard hour: `6` (`python3 -m shared.et guard 6` lets exactly one of the two fires run, summer and winter)
- **Output:** one Notion page per sales, discovery or onboarding call today, inside SURVEN HQ / Call Prep.
  A short text to Joey when at least one page was written.
- **Cost:** most mornings have no sales call, so the run stops after one calendar read and one Python match.
  With calls: per call about 3 web searches, 2 Gmail threads and 1 Fathom summary.

### Prompt
```
You run Call Engine Prep for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m shared.et guard 6   -> if it prints SKIP, stop. Final message: "Call Engine Prep: not this fire."
   (Skip this step if any message in this conversation says "Run now", in a payload block or as a plain message: that is a manual run.)
2b. Check with ToolSearch that the Google Calendar, Notion, Gmail and Fathom connector tools exist. If any is
   missing, stop. Final message: "Call Engine Prep: needs connectors <list>, add them in claude.ai Routines."
3. Read .claude/skills/call_engine/SKILL.md and follow it in prep mode for today (Eastern time). Run every command from /home/user/aca.
Hard rules: never message anyone but Joey; GHL is read-only; never print or look for keys; drafts only.
Final message: one line, as the skill says.
```

## Routine 2: Call Engine Review
- **Schedule:** 9:30pm Eastern, every day.
  - cron (UTC, twin-fired): `30 1,2 * * *`
  - guard hour: `21`
- **Output:** for each new Fathom sales call: one Sales Call Library row (Watched unchecked) with the
  scorecard, and one Gmail draft follow-up to the prospect. For each coaching call: one LS Call Library row
  with 5 takeaways. A short text to Joey when a sales call was reviewed.
- **Cost:** no new recordings means one Notion query, one Fathom list and one Python step, then it stops.
  A reviewed call costs one transcript read and copy (about 6,000 to 15,000 tokens for a 25 to 60 minute
  call) plus the scorecard. At most 3 calls per run.

### Prompt
```
You run Call Engine Review for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m shared.et guard 21   -> if it prints SKIP, stop. Final message: "Call Engine Review: not this fire."
   (Skip this step if any message in this conversation says "Run now", in a payload block or as a plain message: that is a manual run.)
2b. Check with ToolSearch that the Fathom, Notion and Gmail connector tools exist. If any is missing, stop.
   Final message: "Call Engine Review: needs connectors <list>, add them in claude.ai Routines."
3. Read .claude/skills/call_engine/SKILL.md and follow it in review mode. Run every command from /home/user/aca.
Hard rules: never message anyone but Joey; GHL is read-only; never print or look for keys; drafts only; never send an email.
Final message: one line, as the skill says.
```

## Before the first scheduled run (deploy step)
1. Create both routines above in the Surven HQ environment, **disabled**, with the crons, guards and prompts.
2. Joey attaches Fathom, Notion, Google Calendar and Gmail to both routines, then switches them on.
3. Run the backlog once on demand (a session with the connectors): "backfill since 2026-10-01" (repeat
   "run it again" until the final line says 0 waiting). That logs October's discovery calls, their owed
   items and follow-up drafts; the nightly run then only sees new calls.
4. Optional: a dry run of each mode first ("prep tomorrow dry run", "review dry run").

## Pause it
In claude.ai, open Routines, find "Call Engine Prep" or "Call Engine Review" and switch it off. Or ask
Claude: "pause the Call Engine routines".
