# HQ Desk (routine)

- **Name:** HQ Desk
- **Class:** A (fully autonomous: GoHighLevel, the web and an artifact). No connectors needed.
- **Environment:** Surven HQ (`surven_hq` in `config/surven.json`, `env_01LcNf8JTtUumgjrBBnvJ7pK`). It must be
  this one: only the Surven HQ environment's key reads the HQ location and can text Joey.
- **Schedule:** 6:00am Eastern, Monday to Saturday.
  - cron (UTC, twin-fired): `0 10,11 * * 1-6`
  - guard hour: `6` (`python3 -m shared.et guard 6` lets exactly one of the two fires run, in summer and winter)
- **Output:** the HQ Desk artifact (`artifacts.hq_desk` in `config/surven.json`), plus at most one text to Joey.
- **Cost:** one pull (about 90 deals, about 30 seconds of Python), one drafting pass over 15 leads, up to 5 web
  searches. Python does all counting; the model only writes.

## Prompt

```
You run HQ Desk for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. cd /home/user/aca && python3 -m shared.et guard 6   -> if it prints SKIP, stop. Final message: "HQ Desk: not this fire."
   (Skip this step if the conversation has a routine-fire-payload block saying exactly "Run now".)
3. Read /home/user/aca/.claude/skills/hq_desk/SKILL.md and follow it in scheduled mode. Start every shell command with "cd /home/user/aca &&".
Hard rules: never message anyone but Joey; GHL is read-only; never print or look for keys; drafts only.
Final message: one line, as the skill says.
```

## Before the first scheduled run (deploy step)
1. Publish the first page once by hand (on-demand run in the Surven HQ environment), then put its link in
   `config/surven.json` under `artifacts.hq_desk`. Until then each run publishes a new page.
2. Optional: list lead codes Joey never wants on the desk in `config/surven.json` as
   `"hq_desk": {"skip_codes": ["..."]}` (codes only, never names).
3. Create the routine above with the cron, the environment and the prompt. It runs enabled from day one.

## Pause it
In claude.ai, open Routines, find "HQ Desk" and switch it off. Or ask Claude: "pause the HQ Desk routine".
