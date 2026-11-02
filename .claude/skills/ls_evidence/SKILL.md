---
name: ls_evidence
description: Lead Suite Evidence. Builds Joey's private page of proof for the Lead Suite refund guarantee from Surven HQ GoHighLevel. It scores every Lead Suite lead's 6 portal boxes and every booked call's 5 boxes from GHL time stamps, shows the refund scoreboard (qualified booked calls against the contract number, days left in the 90-day window), and lists only the portal rows Joey still has to type in, each with a Copy button. Use it on the Sunday 6am ET schedule (Surven HQ cloud environment), when asked for "lead suite evidence now" (optionally "entered through <date>"), or as a dry run.
---

# Lead Suite Evidence

## Purpose
The Lead Suite contract refunds the fee only if Surven proves every lead was worked with their scored checklist,
with CRM proof, and the portal checklists are complete. The portal has no API, so Joey types each row by hand on
Sundays. This page gives him the exact answers to type and keeps the full proof for the refund file.

## Modes
- **Scheduled** (routine fire, Sunday 6am ET): every step below. Publish the page. No text to anyone.
- **On demand** ("lead suite evidence now"): the same as scheduled. If Joey says what he has already typed in, like
  "entered through Nov 1", pass that date as `--entered-through 2026-11-01` in step 2.
- **Dry run** ("dry run", or a test on another location such as AGC): steps 1 and 2 with `--dry-run`, never step 3.
  Use `--location agc` for the build-time test: `cd /home/user/aca && python3 -m tools.ls_evidence.run --location agc --dry-run`
  (AGC has no Lead Suite leads, so expect zeros). Say what would have been published.

## Inputs
- `config/surven.json`: `ghl.hq` ids (location, `pipelines.leadsuite`, `calendars.discovery_call`,
  `calendars.lead_suite_personal`) and `artifacts.ls_evidence` (the page URL).
- `tools/ls_evidence/settings.json`: the contract target and window, the ads-live date and the pause that does not burn
  the clock, the SOP time windows, the qualified rules, the contract conditions, and the optional
  `portal.entered_through` date.
- Surven HQ GoHighLevel, read-only, through `shared/ghl.py`. This needs the Surven HQ environment.
- The last published page (its hidden state block says which rows were already listed).

## Steps
The repo root is `/home/user/aca` in a routine. In an on-demand session, use the folder where this repo is checked
out instead. Start EVERY command with `cd /home/user/aca &&`. Working files land in `/tmp/ls_evidence/`.

1. **Read the last page.** If `artifacts.ls_evidence` in `config/surven.json` is set, read it with the Artifact tool
   (`action: "read"`, `url` = that link). Note the saved file path it reports; that file is `--prev`. If the setting
   is empty or the read fails, there is no `--prev` (every finished row then counts as new, and the page says so).
2. **Run it.**
   `cd /home/user/aca && python3 -m tools.ls_evidence.run --location hq --prev <file from step 1>`
   - Leave out `--prev` when step 1 gave no file. Add `--entered-through YYYY-MM-DD` only when Joey gave a date.
     Add `--dry-run` in a dry run.
   - If it prints `NO ACCESS`, stop. Final message: `LS Evidence: cannot read Surven HQ GoHighLevel from this environment.`
   - It prints the scoreboard, the SOP rates, the portal row counts, which STL fields it found, and the read errors.
     Python did all the counting and every box. Do not redo it, do not open `raw.json` or `evidence.json`, and never
     pull GHL yourself.
   - If the `fields:` line says STL fields are missing, say so in the final message (the boxes still come from the
     message time stamps, but the field names in HQ may have changed).
3. **Publish** (not in dry run). Artifact `action: "publish"`, `file_path: /tmp/ls_evidence/ls_evidence.html`,
   `url` = `artifacts.ls_evidence`, `description`: "Lead Suite Evidence: refund scoreboard and the portal rows to
   enter." If the setting is empty, publish without `url`, with `icon: "checklist"`, and put the new link in the final
   message so it can be added to `config/surven.json`. Never edit the HTML by hand; Python renders it.

## What lands where
- The page: the Lead Suite Evidence artifact (`artifacts.ls_evidence`), private to Joey. Top to bottom: the refund
  scoreboard and "where the refund case stands", the contract conditions (what GHL can prove and where the rest of
  the proof lives), the rows to type into the portal (portal box order, a Copy button each, and Copy all), the rows
  not finished yet, then the full evidence tables for the refund file (with Copy table buttons).
- Working files in `/tmp/ls_evidence/` only. Nothing is written to GHL, Notion, Gmail or this repo.

## Hard rules
- GoHighLevel is read-only. Never tag, move or edit a record, and never write the STL, Agent or Reply Code fields.
- Never message a lead, Lead Suite, or anyone else. This tool sends nothing, not even a text to Joey.
- Never print, echo or look for an API key.
- No phone numbers or email addresses on the page (Python scrubs them). First names and reply codes only.
- Never invent a box answer or a call note. The notes on a call row come only from a GHL note or the Agent Meeting
  Brief; when there is none, the row asks Joey to write them.
- Refund case wording (if you write anything beyond the final line): never use the word "chargeback", and say
  "contemporaneous transcripts", never "recordings".
- Keep it cheap: one Python run (a few GHL reads per lead, about a minute), no model writing, no web searches.

## Final message format
One line:
`LS Evidence: <the page's top line>. <published | dry run, nothing published>.`
Add ` Fields missing: <list>.` only when step 2 said so, and ` New page: <link>` only on the first publish.
