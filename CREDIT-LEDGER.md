# Credit ledger

These are estimates of the expiring cloud session credits spent on this build. You started with $196 left
of $250; the credits expire Nov 5, 2:59 AM EST.

**How the estimate works.** Opus 5.5 list prices are $4 per million input tokens, $20 per million output
tokens and $0.20 per million cache reads; cache writes cost about $5 to $8 per million. Each agent's cost is
mostly its re-read context (cache reads) plus its own written output. The session doesn't show a live credit
balance, so every row is an estimate with a range. The real balance is on your Claude usage page.

Routines that run AFTER this build (on a schedule) are billed to your normal weekly plan, not these credits.
They run on Sonnet 5.5 and cost about $0.10 to $0.40 per run. See README.md for each routine's weekly runs.

| # | Work | Agents | Est. credits |
|---|------|--------|--------------|
| 1 | Discovery: find the vault and log, read Notion, the repos and the Focus Ledger data, read all 415 log actions | main session | $4 to $6 |
| 2 | Understand workflow: 7 parallel readers (memory notes, repos, Notion, Gmail/Calendar/Fathom/GHL, the log) | 7 | $15 to $25 |
| 3 | Surven HQ GoHighLevel probe session + routine environment test | 2 | $1 to $2 |
| 4 | Build + review workflow: 7 tools, each built then adversarially reviewed and fixed | 14 | (filled in after the run) |
| 5 | Answer Bank page | 1 | (filled in after the run) |
| 6 | Backlog blitz: run each tool on the existing backlog | (later) | (later) |
| 7 | Deploy: artifacts, routines, Notion, README, final checks | main session | (later) |

Running total: filled in at the end.
