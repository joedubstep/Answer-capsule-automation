# Surven automations

Tools that take repeat work off the founder's plate. Each tool drafts; none of them ever sends anything to a lead,
client, family or partner. The only messages that go out are to the operator himself.

The plain-English guide (what each tool does, links to its pages, what to do next) lives in the private Notion page
"Automations (built from the 15-min log)". This file is the technical index.

## Tools

| Tool | Job | Runs | Class |
|---|---|---|---|
| `copy_check` | Checks any draft against the house copy rules and shows the fix. Every other tool gates its drafts through it. Also builds the Copy Checker page. | On demand | Page only |
| `hq_desk` | Morning desk: deals closest to money, drafts, owed items, health flags. Texts the operator only when something new is urgent. | 6:00am ET, Mon to Sat | A |
| `client_desk` | Weekly client admin per care-home client: partner call list, open rooms email draft, owner report, unknown-caller triage. | 7:00am ET, Mon and Fri | A |
| `call_engine` | Pre-call prep pages in Notion; nightly call review into the Sales Call Library, with a follow-up email draft. | 6:30am ET weekdays, 9:30pm ET nightly | B |
| `inbox_desk` | Inbox triage: in-thread reply drafts for cold-email replies, one-page plan PDFs, learning capture, one digest. | 8am and 4pm ET weekdays | B |
| `time_ledger` | Files the 15-minute log into a Notion database with role, task and estimated minutes; weekly time report. | 11:45pm ET nightly | B |
| `lead_list` | Builds the next state's lead batch for the cold-email engine, deduped against everything already emailed. | On demand, on the operator's PC | On demand |
| `ls_evidence` | Lead Suite refund evidence: scores every lead's portal boxes and every booked call from GHL time stamps, shows the refund scoreboard, and lists only the portal rows still to type in. | 6:00am ET Sundays | A |

**Class A** routines need only GoHighLevel (through the environment's proxy key), the web and artifact pages, so
they run as soon as they are scheduled. **Class B** routines also need Gmail, Notion, Fathom or Calendar
connectors. Those are attached in claude.ai Routines, and every class B skill also runs on demand in any session
that has the connectors.

## Layout

```
config/surven.json             non-secret system ids, artifact links, campaign deadline
shared/                        GoHighLevel client (curl, proxy key), Eastern-time twin-fire guard, operator SMS
tools/<tool>/                  code, README, tests
.claude/skills/<tool>/SKILL.md runbook the routine or an on-demand session follows
routines/<tool>.md             schedule, environment, connectors, exact routine prompt
BUILD-SPEC.md                  rules every tool follows
CREDIT-LEDGER.md               build cost estimates
```

## Tests

From the repo root: `python3 -m unittest discover -s tools/<tool>/tests -t .` (688 tests across the 8 tools,
offline, synthetic fixtures only).

## Privacy

This repo is public so routines can clone it without credentials. It holds no personal data and no business
results; test data is made up. Real outputs land in private artifact pages, Notion and Gmail drafts.
