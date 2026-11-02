---
name: hq_desk
description: Surven HQ Deal Desk. Builds Joey's morning desk page from Surven HQ GoHighLevel. It shows who is closest to money today, why, the next step, a ready draft for each lead, drafts of what he owes, and health flags. Then it texts Joey only if something is new and urgent. Use it on the 6am ET schedule (Mon to Sat, Surven HQ cloud environment), when asked to "run the desk now", or as a dry run.
---

# HQ Desk

## Purpose
Answer one question each morning: who is closest to money today, what exactly does Joey send or bring them, and
what is broken. The follow-up planner still plans the calls and texts per lead. The desk does not replace it.

## Modes
- **Scheduled** (routine fire): every step below. Publish the page. Text Joey only if step 9 says so.
- **On demand** ("run the desk now"): the same as scheduled.
- **Dry run** ("dry run", or a test on another location such as AGC): every step except publishing (step 8)
  and texting (step 9). Use `--location <key>` (`agc`, `splendor`) in steps 1 and 7 for another location, and
  add `--dry-run` to step 7. Say what would have been published and texted.
  The quick test with no drafts: `cd /home/user/aca && python3 -m tools.hq_desk.run --location agc --dry-run`

## Inputs
- `config/surven.json`: `ghl.hq` ids, `campaign.price_raise_deadline_et`, `artifacts.hq_desk` (the page URL),
  and the optional `hq_desk.skip_codes` (lead codes Joey said never to work).
- Surven HQ GoHighLevel, read-only, through `shared/ghl.py`. This needs the Surven HQ environment.
- `list_triggers`, if this session has it, to find Surven routines whose last run failed.
- WebSearch and WebFetch, only for regulation or licensing questions that a lead is owed an answer to.

## Steps
The repo root is `/home/user/aca` in a routine. In an on-demand session, use the folder where this repo is
checked out instead. Start EVERY command with `cd /home/user/aca &&` (the shell may not keep the folder between
commands, and the commands only work from the repo root). Working files land in `/tmp/hq_desk/`.

1. **Data.** `cd /home/user/aca && python3 -m tools.hq_desk.run --location hq --stage data`
   - If it prints `NO ACCESS`, stop. Final message: `HQ Desk: cannot read Surven HQ GoHighLevel from this environment.`
   - It prints the counts and the red flags. Python did all the counting. Do not redo it.
2. **Read** `/tmp/hq_desk/brief.json` only. It holds the top 15 leads with their context. Never open `raw.json`
   or `desk.json` (they are big) and never pull GHL yourself.
3. **Write drafts** to `/tmp/hq_desk/drafts.json`: one JSON object keyed by each lead's `id` (format below).
   Your judgment calls:
   - **Who gets a draft:** the top 10 leads get a text or an email. Use `suggest`: `sms` for Lead Suite and
     warm referral leads, `email` for cold email repliers (E codes). Write one draft per lead, never both,
     unless they wrote on both channels.
   - **What it says:** reference the real context. Use what they said (`context.last_inbound`), what was offered
     on the call (`context.offers`), what Joey last sent (`context.last_from_joey`), the plan log, and the
     deadline (`context.price_raise`) when the lead has the `price raise` chip. Answer what they asked, in order.
   - **Owed items** (`owed`, each with its index `i`): deliver each one you can, for every lead in the brief.
     For a regulation or licensing question, use WebSearch, read the primary source (the state agency, the
     statute, the county office), and put the links in `sources`. Never invent a fact or a result. Surven has no
     client results yet, so say "market benchmark" if a number is needed. If the item needs something only Joey
     has (a Loom, a number from his notes, a call he promised, a document, the price he quoted), write a
     `missing` line that says exactly what is missing, like "Your Loom walkthrough. Record it, then send this
     text."
   - **Spoken material** (a call he owes, an opener): never a script. Put facts and likely objections as short
     bullets in an owed item of `kind` `note`, or in `note` (BUILD-SPEC rule 6).
   - **`action`:** replace the suggested next step only if the record shows a better one.
   - **`hide`:** take a lead off today's desk, with a short reason, when it should not be there. Examples: the
     "hot" message is an auto-reply or a plain "thanks" that needs no answer, Joey already answered outside
     GoHighLevel (the plan log says so), the plan log or picture says Joey dropped them, a death in the family,
     a paid client, a vendor or a partner, or a code Joey said to skip. A hidden lead also leaves the red flag
     counts.
4. **Voice for every draft** (Joey's locked rules, BUILD-SPEC rule 5, `tools/copy_check/rules.json`):
   - Texts: one or two short sentences, under 160 characters. Emails: under 80 words, a short plain subject,
     signed `Joey` and nothing else.
   - 4th-grade words, US English, plain short sentences. No em or en dashes, no emojis, no buzzwords, no
     metaphors, no idioms. State it and stop.
   - One ask: ONE question of 2 to 5 words. Put their own word in the question so it shows you read them.
   - No greeting by name and no "it's Joey with Surven" unless this is the first message they ever get
     (a warm referral). Never repeat back what they said. "Okay", never "Got it".
   - Name the situation, never the person. "Residents" not "patients", "families" not "leads". Never "care home"
     or "enquiry". Never "audit", "assessment", "grade", "score", or "is now a bad time". Never promise a call at
     a set time; ask when works.
   - No price, no dollar amount, no percent and no statistic in any draft, even for a lead who heard the price on
     a call. The copy checker blocks all of them. If an owed item needs the number (a proposal, a quote), write
     the draft without it and put "Add the price you quoted on the call" in `missing`.
   - Never mention case studies, client results, testimonials or success stories. Surven has none yet and the
     checker blocks them. If an owed item promised case studies, say in `missing` that Joey must pick what to
     send.
   - "Let me think about it" or "I need to talk to my partner": a 1 to 4 word acknowledgement only, like
     "Of course, take your time." Set `action` to a call from Joey in a couple of days.
   - A buying question (price, terms) goes to a call: say it is easier on a quick call and ask when they are free.
   - Price raise: only for leads with the `price raise` chip. Say the price goes up at 8pm their time on the
     date in `context.price_raise.deadline` (write it like "8pm your time on Wednesday, November 18"). Never
     the percent, never the new price. The planner sends the campaign emails; do not copy them.
   - No phone numbers and no email addresses in any draft, note or `missing` line. A draft that has one is held.
     Point to the source link instead.
   - You may check one draft while writing:
     `cd /home/user/aca && python3 -m tools.copy_check.check --context prospect_sms --text "..." --json`
     (or `prospect_email`). If `tools/copy_check` is missing, step 7 runs a basic check and the page says so.
5. **Read the last page.** If `artifacts.hq_desk` in `config/surven.json` is set, read it with the Artifact
   tool (`action: "read"`, `url` = that link). Note the saved file path it reports; that file is `--prev`.
   If the setting is empty, or the read fails, there is no `--prev` (everything then counts as new).
6. **Routine health.** Look for the `list_triggers` tool (ToolSearch query `list_triggers`). If it is there,
   call it once with `{"enabled": true, "recurring": true, "limit": 100}` and write `/tmp/hq_desk/routines.json`
   as a JSON list of `{"name": <name>, "status": <last_run.status, or "" when there is no last_run>}`, one per
   scheduled task. If the tool is not there, write `{"unavailable": "list_triggers is not in this session"}`.
7. **Check and render.**
   `cd /home/user/aca && python3 -m tools.hq_desk.run --location hq --stage page --prev <file from step 5> --routines /tmp/hq_desk/routines.json`
   - Leave out `--prev` when step 5 gave no file. Add `--dry-run` in a dry run.
   - It runs every draft through the copy checker, merges the drafts, renders `/tmp/hq_desk/hq_desk.html`,
     and decides on the text.
   - Exit 1 means a draft is HELD (or drafts.json is not valid JSON; the line says so). Each
     `HELD <code> <draft>: <rule>: <match>` line says why. Rewrite only those drafts in `drafts.json` (keep the
     meaning, fix the rule) and run step 7 again; it starts clean each time. After two rounds, leave anything
     still held; the page shows it as held and never shows its text.
   - A `skip <code> owed for=...` line means that owed draft's `for` is not one of the lead's `i` values, so it
     was dropped. Fix the `for` and run step 7 again.
   - `warn` lines are fine. The page shows the warning next to the draft for Joey.
8. **Publish** (not in dry run). Artifact `action: "publish"`, `file_path: /tmp/hq_desk/hq_desk.html`, `url` =
   `artifacts.hq_desk`, and `description`: "Surven HQ Deal Desk: who is closest to money today." If the setting
   is empty, publish without `url`, with `icon: "briefcase"`, and put the new link in the final message so it
   can be added to `config/surven.json`.
9. **Text Joey** (not in dry run). Only if step 7 printed `TEXT:` (the file `/tmp/hq_desk/sms.txt` exists):
   `cd /home/user/aca && python3 -m shared.notify --file /tmp/hq_desk/sms.txt`. Step 7 asks for a text only when
   there is a new hot lead, an owed item newly drafted, or a health flag that just turned red. notify holds
   texts in quiet hours. If step 7 printed `NO TEXT`, send nothing.

## drafts.json format
```json
{
  "<lead id>": {
    "sms": "text draft",
    "email_subject": "subject", "email": "email body",
    "action": "optional better next step",
    "note": "optional one line for Joey",
    "hide": "optional reason to leave this lead off today",
    "owed": [{"for": 0, "kind": "email|sms|note", "subject": "", "text": "the deliverable",
              "sources": ["https://..."], "missing": "what only Joey has",
              "done": "only when the plan log shows it was already done, with the date; then no text"}]
  }
}
```
`for` is the owed item's `i` from the brief. `kind` `note` is words for Joey, not the lead. An owed item with
`done` shows on the page as "Looks done already" and never triggers a text. Leave out a key you do not use.

## What lands where
- The page: the HQ Desk artifact (`artifacts.hq_desk`), private to Joey. A top line, health flags, then up to 15
  lead cards: first name, home, code, why now, days waiting, the next step, the draft with a copy button, and
  owed drafts folded under each card.
- One text to Joey, only when something is new and urgent, through Surven HQ (`shared/notify.py`).
- Working files in `/tmp/hq_desk/` only. Nothing is written to GHL, Notion, Gmail or this repo.

## Hard rules
- Never message a lead, client, family or partner. Drafts only. The one text goes to Joey.
- GoHighLevel is read-only. Never tag, move or edit a record, and never write the planner's fields.
- Never print, echo or look for an API key.
- Every draft passes the copy checker before it reaches the page (step 7 enforces it).
- No phone numbers or email addresses on the page or in a draft.
- Verify facts. Every fact a lead could see comes from a primary source with a link, or from their own record.
- Keep it cheap: Python counts and joins, you only write. At most 5 web searches a run.

## Final message format
One line:
`HQ Desk: <the page's top line>. <texted Joey | no text | dry run, nothing published or texted>.`
Add ` New page: <link>` only on the first publish.
