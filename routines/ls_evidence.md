# LS Evidence (routine)

- **Name:** LS Evidence
- **Class:** A (fully autonomous: GoHighLevel and an artifact). No connectors needed.
- **Environment:** Surven HQ (`surven_hq` in `config/surven.json`, `env_01LcNf8JTtUumgjrBBnvJ7pK`). It must be this
  one: only the Surven HQ environment's key reads the HQ location, where the Lead Suite leads live.
- **Schedule:** 6:00am Eastern every Sunday, so the page is fresh for Joey's Sunday "/update LS portal" block. Also on
  demand ("lead suite evidence now").
  - cron (UTC, twin-fired): `0 10,11 * * 0`
  - guard hour: `6` (`python3 -m shared.et guard 6` lets exactly one of the two fires run, in summer and winter)
- **Output:** the Lead Suite Evidence artifact (`artifacts.ls_evidence` in `config/surven.json`). No texts.
- **Cost:** one Python run (a few read-only GHL calls per lead, about a minute). The model only reads the
  last page, runs one command and publishes. No drafting, no web searches.
- **When it stops being useful:** the 90-day window ends Nov 16, 2026 (see `tools/ls_evidence/settings.json`). Keep it
  running until the refund question is settled, then pause it.

## Prompt

```
You run LS Evidence for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. cd /home/user/aca && python3 -m shared.et guard 6   -> if it prints SKIP, stop. Final message: "LS Evidence: not this fire."
   (Skip this step if any message in this conversation says "Run now", in a payload block or as a plain message: that is a manual run.)
3. Read /home/user/aca/.claude/skills/ls_evidence/SKILL.md and follow it in scheduled mode. Start every shell command with "cd /home/user/aca &&".
Hard rules: never message anyone; GHL is read-only; never print or look for keys; publish only the page Python built.
Final message: one line, as the skill says.
```

## Before the first scheduled run (deploy step)
1. Run it once on demand in the Surven HQ environment ("lead suite evidence now") so it publishes the first page, then
   add its link to `config/surven.json` as a new key `artifacts.ls_evidence` (the key does not exist yet). Until then each run publishes a new page and
   cannot tell which rows were already listed.
2. Check the run's `fields:` line. If an STL field shows as missing, its name in HQ differs from what
   `tools/ls_evidence/profile.py` looks for; add the HQ name there.
3. Optional: if Joey's portal is complete up to a date, set `portal.entered_through` in
   `tools/ls_evidence/settings.json` to that date (or say "lead suite evidence now, entered through <date>"), so the
   first page does not list rows he already typed.
4. Create the routine above with the cron, the environment and the prompt. It runs enabled from day one.

## Pause it
In claude.ai, open Routines, find "LS Evidence" and switch it off. Or ask Claude: "pause the LS Evidence routine".
