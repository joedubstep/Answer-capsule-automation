# Client Desk (two routines)

- **Class:** A (fully autonomous: GoHighLevel, an artifact and a push notification). No connectors needed.
- **Runbook:** `.claude/skills/client_desk/SKILL.md`. Code: `tools/client_desk/`.
- **Schedule:** 7:00am Eastern, Monday and Friday.
  - cron (UTC, twin-fired): `0 11,12 * * 1,5`
  - guard hour: `7` (`python3 -m shared.et guard 7` lets exactly one of the two fires run, in summer and winter)
- **Output:** one private desk page per client (`artifacts.client_desk_agc`, `artifacts.client_desk_splendor` in
  `config/surven.json`), one private owner report page per client updated on Fridays
  (`artifacts.client_desk_agc_report`, `artifacts.client_desk_splendor_report`), plus one push notification to Joey.
  No SMS: only the Surven HQ environment can text Joey.
- **Cost:** one read-only pull (about a minute of Python and about 200 GoHighLevel reads for AGC, mostly one read per
  conversation with activity in the last 45 days), an optional short notes file, one render. The model only reads a
  2 KB brief. Two runs a week per client, so four runs a week.

Each routine must run in its client's environment, because each environment holds only that client's GoHighLevel key.

## Routine 1: Client Desk: AGC

- **Name:** Client Desk: AGC
- **Environment:** Default (`default_agc` in `config/surven.json`, `env_01UkFtCmXo2vwSWjK2qkhgF2`)
- **Cron:** `0 11,12 * * 1,5`

```
You run Client Desk for Joey (Surven), client agc. Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m shared.et guard 7   -> if it prints SKIP, stop. Final message: "Client Desk AGC: not this fire."
   (Skip this step if any message in this conversation says "Run now", in a payload block or as a plain message: that is a manual run.)
3. Read .claude/skills/client_desk/SKILL.md and follow it in scheduled mode with client agc. Run every command from /home/user/aca.
Hard rules: never message anyone but Joey; GHL is read-only; never print or look for keys; drafts only.
Final message: one line, as the skill says.
```

## Routine 2: Client Desk: Splendor

- **Name:** Client Desk: Splendor
- **Environment:** Splendor (`splendor` in `config/surven.json`, `env_01KKsZkwureeTEvfSUyZmmm5`)
- **Cron:** `0 11,12 * * 1,5`

```
You run Client Desk for Joey (Surven), client splendor. Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m shared.et guard 7   -> if it prints SKIP, stop. Final message: "Client Desk Splendor: not this fire."
   (Skip this step if any message in this conversation says "Run now", in a payload block or as a plain message: that is a manual run.)
3. Read .claude/skills/client_desk/SKILL.md and follow it in scheduled mode with client splendor. Run every command from /home/user/aca.
Hard rules: never message anyone but Joey; GHL is read-only; never print or look for keys; drafts only.
Final message: one line, as the skill says.
```

## Before the first scheduled run (deploy step)
1. Add four empty keys to `config/surven.json` under `artifacts` if they are not there yet: `client_desk_agc`,
   `client_desk_agc_report`, `client_desk_splendor`, `client_desk_splendor_report`.
2. In each environment, run the skill once on demand on a Friday, or ask for the full desk on another day ("client desk
   agc now" in the Default environment, "client desk splendor now" in the Splendor environment). It publishes the desk
   page and the report page and prints both links.
3. Put the four links in `config/surven.json` under those keys. Until then each run publishes new pages.
4. Splendor: open its first page and check the footer line. It says which family pipeline and tour calendar were found
   by name. If either says "none" or "fallback id", fix the names or ids in `tools/client_desk/clients.json`.
   Confirm the Splendor goal there too (it reads "6 tours by Jan 13" from the planner's client notes).
5. Create the two routines above with their cron, environment and prompt. They run enabled from day one.

## Pause it
In claude.ai, open Routines, find "Client Desk: AGC" or "Client Desk: Splendor" and switch it off. Or ask Claude:
"pause the Client Desk routines".
