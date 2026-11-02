# Lead List: no routine (on demand)

- **Name:** Lead List
- **Schedule:** none. Do not create a routine for this tool.
- **Where it runs:** a Claude session on Joey's PC (open web, and the engine repo `C:\dev\surven-outreach` with
  its state pulled). A cloud session can run only the tests: `runway` and `build` need the engine's state files,
  which live in a private repo a cloud session cannot clone.
- **Class:** on demand. No GoHighLevel key and no connectors needed.
- **Artifact:** none. The output is a batch folder plus `review.csv`; Joey approves in the chat.

## Why there is no schedule

1. **The network.** Tested 2026-11-02 from this repo's cloud environment: every state license site (FL, NC, AZ,
   MI, TN, VA, WA), DuckDuckGo and ordinary websites were refused by the environment's network policy (proxy 403),
   and WebFetch was refused the same way. The tool needs the state site, a search engine and each home's own
   website. Joey's PC has all three.
2. **The load.** `queue.json`, `lead_facts.json` and `build/prospects.json` are PC-owned files in the PRIVATE
   repo `joedubstep/surven-carehome-state`. A cloud routine cannot clone a private repo, and the load must follow
   `tools/cloud_state.py push-local` on the PC.
3. **Joey's OK.** Every batch is shown to Joey before it is loaded.
4. **Cost.** A state is built once. A schedule would spend credits to find nothing new.

## How Joey starts it

In a Claude session on the PC: "build the next state list for Florida" (or North Carolina, or any state; the
skill adds a module for a new one). The session follows `.claude/skills/lead_list/SKILL.md`.

## If it ever moves to the cloud

Only if Joey wants the building (not the loading) in the cloud:
1. Give a cloud environment full network access (claude.ai, the environment's settings, Network access). The
   hosts it needs are the state site (e.g. `quality.healthfinder.fl.gov`, `info.ncdhhs.gov`),
   `html.duckduckgo.com`, and any home's website, which is why an allow list is not enough.
2. The prompt would clone this repo, read the private state through a deploy key or a GitHub connector, run the
   skill's steps 1 to 8 in dry run mode, and text Joey the counts with `shared/notify.py`. Loading stays on the PC.
