# Build spec for the Surven automation tools

This file is for the agents and people who build and maintain these tools. Joey reads `README.md`, not this.

## Why these tools exist

Joey Gargiulo runs Surven, a small agency that fills empty beds for assisted living homes. His 15-minute log
(415 actions, 10/15 to 11/1) and his live systems show three things:

1. Planning is already automated. Three follow-up agents and a Morning Sales Brief run every morning.
2. The work AFTER the plan is the bottleneck. That covers approvals, the YOU OWE promises (17 open, oldest 42
   days), cold-email replies nobody worked (22 sitting at "Replied"), call prep and call review (about 4 hours
   around a single 24-minute call), weekly client admin, and log upkeep.
3. Sales are stalled. November shows $0 against a $10K goal, there are no discovery calls booked in the next
   14 days, and 11 owners have been pitched and are waiting.

Every tool must save Joey real minutes or move money. If it does neither, don't build it.

Sources the builders read (scratchpad, read-only, may hold personal data; NEVER copy personal data into this repo):
`/tmp/claude-0/-home-user-Answer-capsule-automation/fa962b56-ce6a-4c38-9e17-4366affe22db/scratchpad/`
- `understand/log.json`: the ranked 15-minute-log analysis
- `understand/live-systems.json`: Gmail, Calendar, Fathom and AGC GHL findings
- `understand/repos-*.json`: the existing automations and reusable code
- `understand/notion.json`: Notion SOPs, databases and ids
- `understand/memory-*.json`: business brief, locked rules, decisions
- `log_actions.txt`: all 415 log actions; `master-dash/blobs/bf92f955550abff5666014e879f732d0.csv` is the
  labeled version (role, task and kind per action)
- `hq_probe.txt`: Surven HQ GHL inventory (pipelines, stages, fields, calendars)

Existing repos are cloned read-only under `/home/user/`. Reuse their patterns and never edit them:
`morning-sales-brief`, `follow-up-system-agent-repo`, `joedubstep/surven-carehome`, `surven-carehome-state`.

## Where tools run (tested 2026-11-02)

A cloud routine created from a Claude session runs as follows:
- It runs on Sonnet 5.5 with no repo checked out. Its first step clones this repo:
  `git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca`
  The repo is public, so this works without credentials. Private repos do NOT clone.
- It gets the GoHighLevel key of its ENVIRONMENT through the proxy. See `shared/ghl.py` and `config/surven.json`:
  - Default env: AGC
  - Surven HQ env: Surven HQ
  - Splendor env: Splendor
- It has Bash, Python 3.11 (stdlib only, no pip), node, WebSearch, WebFetch, Artifact, ArtifactData and
  PushNotification.
- It has NO MCP connectors: no Gmail, Notion, Fathom, Calendar or Drive. Joey can attach those to a routine
  in claude.ai under Routines.

That gives two classes of tool:
- **Class A, fully autonomous.** These need only GHL, the web and artifacts, so they run as soon as they are
  scheduled.
- **Class B, needs connectors.** These need Gmail, Notion, Fathom or Calendar. The routine is created
  DISABLED. Joey attaches the connectors and switches it on. Every class B skill also works ON DEMAND in any
  Claude session that has the connectors (open a session on this repo and run the skill).

## Repo layout

```
README.md                      plain-English index for Joey (what each tool does, where output lands)
BUILD-SPEC.md                  this file
CREDIT-LEDGER.md               credit spend estimates
config/surven.json             non-secret ids (locations, pipelines, Notion ids, artifact urls, deadline)
shared/ghl.py                  curl GHL client, paginated readers, GHL_FAKE_DIR test hook
shared/et.py                   Eastern time helpers + twin-fire guard: `python3 -m shared.et guard 6`
shared/notify.py               text Joey via HQ GHL (HQ env only), quiet hours, split, read-back
tools/<tool>/                  python package for the tool: *.py, README.md, tests/ (unittest)
.claude/skills/<tool>/SKILL.md the runbook the routine (or an on-demand session) follows
routines/<tool>.md             schedule, environment, connectors, and the exact routine prompt
```

Run every tool from the repo root: `python3 -m tools.<tool>.<module> ...`. Tests:
`python3 -m unittest discover -s tools/<tool>/tests -t .` from the repo root.

## Hard rules for every tool

1. **Never message a prospect, client, family or partner.** Output is a draft for Joey to approve:
   - a Gmail draft
   - a Notion page or row
   - an artifact page
   - copy text with a copy button
   - the one exception: an SMS or push notification to Joey himself

   Never write to the GHL fields the follow-up planner owns (Agent *, STL *, Reply Code). Never tag, move or
   edit GHL records. GHL is READ-ONLY for these tools; the only GHL write allowed is `shared/notify.py`
   texting Joey.
2. **No personal data in this repo.** It is PUBLIC. Tests use synthetic fixtures with names like "Pat Example".
   Real outputs go to artifacts, Notion, Gmail drafts, or `/tmp`.
3. **Never print, echo or look for an API key.**
4. **Every piece of prospect- or client-facing text passes the copy checker** before it lands anywhere:
   `python3 -m tools.copy_check.check --context <prospect_email|prospect_sms|client|internal> --file <path> --json`
   prints JSON `{"ok": bool, "issues": [{"rule","severity","match","line","fix"}]}`. Exit 0 means no blocking
   issues, 1 means blocking issues, 2 means a bad argument or a checker error (never treat 2 as passed). Fix the blocking issues; show any warnings to Joey next to the draft.
5. **Copy voice** (Joey's locked rules, full list in `tools/copy_check/rules.json`):
   - no em or en dashes
   - US English
   - 4th-grade reading level, short plain sentences
   - no buzzwords, no metaphors or idioms
   - state it and stop
   - the ask is ONE question of 2 to 5 words
   - name the situation, never the person
   - "residents" not "patients", "families" not "leads"
   - never "care home" or "enquiry" in client-facing text
   - no price before a call
   - no statistics in prospect copy
   - never "audit", "assessment", "grade" or "score" in cold outreach
   - never "is now a bad time"
   - no emojis in outreach
   - never invent client results: Surven has no client results yet, so say "market benchmark" instead
6. **Joey writes anything he says out loud** (call scripts, VSLs, openers). For spoken material, give bullets,
   facts and objections, never a finished script.
7. **Verify facts.** Every fact a prospect could see must come from a primary source with a link. Mark
   anything inferred as inferred.
8. **No Meta automation of any kind.** Never connect to or post on Meta surfaces.
9. **Keep runs cheap.** Routines bill to Joey's weekly plan. Exit early when there is nothing new. Do the
   counting and joins in Python, not in the model. Ask the model only for judgment and writing. Keep context
   small: never dump whole databases or inboxes.
10. **Plain English for Joey.** He does not read code. Artifact pages and messages say what to do in short
    sentences. US English, no em dashes.

## Routine pattern (copy this shape)

`routines/<tool>.md` holds:
- **Name, environment, schedule.** The cron is UTC and twin-fired, e.g. `0 10,11 * * 1-5` for 6am ET on
  weekdays.
- **The class** (A or B), plus the connectors needed for class B.
- **The exact prompt:**

```
You run <Tool> for Joey (Surven). Steps:
1. git clone --depth 1 -b claude/magical-wozniak-p9jwct https://github.com/joedubstep/Answer-capsule-automation /home/user/aca && cd /home/user/aca
2. python3 -m shared.et guard <hour>   -> if it prints SKIP, stop. Final message: "<Tool>: not this fire."
   (Skip this step if the conversation has a routine-fire-payload block saying exactly "Run now".)
3. Read .claude/skills/<tool>/SKILL.md and follow it in scheduled mode.
Hard rules: never message anyone but Joey; GHL is read-only; never print or look for keys; drafts only.
Final message: one line, as the skill says.
```

For class B, step 2b is: check that the needed connector tools exist (ToolSearch). If they are missing, write
the one-line final message `<Tool>: needs connectors <list>, add them in claude.ai Routines.` and stop.

## Skill pattern (`.claude/skills/<tool>/SKILL.md`)

Frontmatter: `name`, `description` (when to use it). Sections:
- Purpose (2 lines)
- Modes: scheduled / on-demand ("run it now") / dry run (no writes, no texts, print what would happen)
- Inputs
- Steps (numbered, exact commands)
- What lands where
- Hard rules
- Final message format

Deterministic work lives in Python. The skill tells the model exactly which commands to run, which judgment
calls are its own, and the exact output contract (files, artifact url, text length).

## Artifact pages

Class A tools publish to ONE fixed private artifact per tool. The URL lives in `config/surven.json`
`artifacts.<tool>` and is filled in after the first publish. The routine reads the artifact first
(`Artifact` action read), then publishes the new HTML with `url`.

Page design:
- phone-first, plain HTML, no external scripts
- the brand palette: cream `#f2eee3`, paper `#faf7ef`, sage `#4e6242`, ink `#181b18`, hairline `#c8c1b1`
- dark mode via `prefers-color-scheme`
- copy buttons for drafts
- a "last updated <ET time>" line
- no phone numbers and no full email addresses on the page: use first name + home name + the lead's code
  (e.g. 41 or E24), since Joey texts a code to bridge a call

Python renders the HTML, e.g. `python3 -m tools.<tool>.render --out /tmp/<tool>.html`, so the model only
transports it.

## Deliverables per tool

1. Code with tests that pass offline (`GHL_FAKE_DIR` fixtures, synthetic data).
2. `tools/<tool>/README.md`: plain English for Joey. What it does, when it runs, where the output lands, what
   he does with it, the minutes it saves, and how to pause it.
3. `.claude/skills/<tool>/SKILL.md` and `routines/<tool>.md`.
4. A live READ-ONLY smoke test where possible: AGC GHL is readable from this build session through
   `shared.ghl`, and the connectors are readable through MCP. NO writes, sends, drafts or publishes during
   the build.
5. A final report: files written, test results, smoke-test results, known gaps, and the exact things the
   deploy step must do (artifacts to create, Notion databases to create, config keys to fill).

Builders: write ONLY inside your own `tools/<tool>/`, `.claude/skills/<tool>/` and `routines/<tool>.md`.
Do not edit `shared/` or `config/`; if you need a change there, put it in your report. Do not run git. Do not
create routines, artifacts, Notion pages or Gmail drafts.
