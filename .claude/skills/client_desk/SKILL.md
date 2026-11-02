---
name: client_desk
description: Client Desk, the weekly client admin for Surven's care-home clients (AGC and Splendor). Monday 7am ET it builds the referral partner call list, the open rooms email draft and the unknown-caller triage. Friday 7am ET it builds the owner's weekly report (a page and a short text) and the triage. Use it on the schedule (AGC in the Default environment, Splendor in the Splendor environment), when asked "client desk agc now" or "client desk splendor now", or as a dry run.
---

# Client Desk

## Purpose
Do the weekly client admin Joey does by hand: the owner's Friday report, the Monday open rooms email to referral
partners, the partner call list, and "robocall or family?" for every unknown caller. Joey checks and sends; nothing
goes to a client, family or partner from here.

## Modes
- **Scheduled** (routine fire): `--mode auto`. Monday builds the Monday desk, Friday builds the Friday desk. Every
  step below. Publish the desk page (and on Fridays the report page), push one line.
- **On demand** ("client desk agc now", "client desk splendor now"): `--mode auto`. On a Tuesday, Wednesday,
  Thursday or weekend day it builds everything (`full`). If Joey names a day ("client desk agc friday"), pass
  `--mode monday` or `--mode friday`. Otherwise the same as scheduled.
- **Dry run** ("dry run", or a build session): add `--dry-run` to steps 1 and 5, and skip steps 4, 6 and 7. Say what
  would have been published and pushed. Example: `python3 -m tools.client_desk.run --client agc --mode friday --dry-run`
  runs steps 1 and 5 in one go.

`<client>` below is `agc` or `splendor`. The environment must hold that client's GoHighLevel key: AGC is the Default
environment, Splendor is the Splendor environment.

## Inputs
- `tools/client_desk/clients.json`: per-client ids, the goal, the partner target, the open rooms email words.
- `config/surven.json`: the location id, `artifacts.client_desk_<client>` (this client's desk page link) and
  `artifacts.client_desk_<client>_report` (this client's owner report page link).
- The client's GoHighLevel location, read-only, through `shared/ghl.py`.

## Steps
Run everything from the repo root. Files land in `/tmp/client_desk/<client>/`.

1. **Data.** `python3 -m tools.client_desk.run --client <client> --mode auto --stage data`
   - If it prints `NO ACCESS`, stop. Final message: `Client Desk <AGC|Splendor>: cannot read GoHighLevel from this environment.`
   - It prints every count (families, tours, move-ins, partner stages, activity, callers). Python did the counting
     and the joins. Do not redo them and do not pull GoHighLevel yourself.
2. **Read** `/tmp/client_desk/<client>/brief.json` only. Never open `raw.json` or `view.json` (they are big).
3. **Judgment, only if needed.** Write `/tmp/client_desk/<client>/notes.json`, or skip this step (most weeks):
   ```json
   {"triage": {"<caller id>": {"verdict": "family-likely|robocall-likely|not-a-family|unclear", "reason": "a few words"}},
    "report_note": "optional, at most 2 short sentences for the owner"}
   ```
   - **Callers.** `brief.callers` holds only the callers that are not clear robocalls, with what they said (`heard`)
     and any text (`texts`). Change a verdict only when those words plainly say something else (a caller asking
     about a job is not a family; one asking about a room for a parent is). No words means it stays as it is: never
     guess. Never touch a caller who is not in the brief.
   - **Report note** (Friday or full only). Leave it out unless brief.json shows something the owner must hear that
     the report does not say. Facts from brief.json only, no new numbers, Joey's voice: short plain sentences, US
     English, no dashes, "families" not "leads", "residents" not "patients", never "care home". The page step
     checks it and leaves it out if it breaks a rule.
4. **Read the last pages.** For each of `artifacts.client_desk_<client>` and (Friday or full only)
   `artifacts.client_desk_<client>_report` in `config/surven.json` that is set, read it with the Artifact tool
   (`action: "read"`, `url` = that link) so this run can update it in place. Do not study what comes back. An empty
   setting means that page has not been published yet.
5. **Check and render.** `python3 -m tools.client_desk.run --client <client> --stage page`
   - It applies notes.json, runs every client-facing text through the copy checker, and writes
     `client_desk.html` (the desk), `report.html` (Friday or full), `report.txt`, `email.txt` (Monday or full)
     and `push.txt` (one line).
   - Exit 1 means something is `HELD` by the copy checker. A held report note is already left out. A held report or
     email comes from the words in `clients.json` or the home's name; do not edit code or config in a routine. The
     page says it is held and does not show it. Say so in the final message.
6. **Publish** (not in dry run). Two pages, each its own private artifact. Never use the `files` field.
   - a. The desk: Artifact `action: "publish"`, `file_path: /tmp/client_desk/<client>/client_desk.html`,
     `url` = `artifacts.client_desk_<client>`, `description`: "Client Desk for <home>: report, partner calls, open
     rooms email and caller triage." If the setting is empty, leave out `url`, add `icon: "clipboard"`, and put the
     new link in the final message.
   - b. Only when `/tmp/client_desk/<client>/report.html` exists (Friday or full): the owner report, Artifact
     `action: "publish"`, `file_path: /tmp/client_desk/<client>/report.html`, `url` =
     `artifacts.client_desk_<client>_report`, `description`: "Weekly owner report for <home>." If the setting is empty,
     leave out `url`, add `icon: "report"`, and put the new link in the final message.
   - New links go into `config/surven.json` by hand later (deploy step). A routine never edits the repo.
7. **Push** (not in dry run). Load PushNotification with ToolSearch (`select:PushNotification`) and send the one
   line in `/tmp/client_desk/<client>/push.txt`, plus the desk page link. Never send an SMS from here: the Default and
   Splendor environments cannot text Joey (`shared/notify.py` works only in Surven HQ). If PushNotification is not
   available, skip it and say so in the final message.

## What lands where
- **The desk page** (`artifacts.client_desk_<client>`, private to Joey): the top line, the numbers, unknown callers
  with a verdict and the reason (only "Caller" + last 4 digits), messages waiting over 24 hours, and:
  - Monday: partner calls in four groups (not reached yet, two-week check-in, the weekly email list, thank-you due),
    oldest touch first, with what to ask as bullets; the open rooms email with copy buttons and `[N]` blanks; a
    one-line text to the owner asking which rooms are open.
  - Friday: the owner report preview, a link to the report page, and the short text with a copy button.
- **The report page** (`artifacts.client_desk_<client>_report`, private to Joey, Friday or full runs): the owner
  report in Surven's brand. Joey opens it, checks it, and sends the client a screenshot of it or sends the short
  text. Never share the desk link with a client: it lists partners and callers.
- **One push notification** to Joey.
- Working files in `/tmp/client_desk/<client>/` only. Nothing is written to GoHighLevel, Notion, Gmail or this repo.

## Hard rules
- Never message a client, family or partner. Drafts only. The one push goes to Joey.
- GoHighLevel is read-only. Never tag, move or edit a record, and never write the planner's fields.
- Never print, echo or look for an API key.
- Every client-facing text passes the copy checker before it reaches the page (step 5 enforces it).
- No phone numbers and no email addresses on the page or in a draft. Unknown callers show only the last 4 digits.
- Numbers come from Python only. Zero is zero; never estimate, round up or invent a result.
- Spoken material (partner calls) is bullets of what to ask, never a script. Joey says his own words.
- Keep it cheap: one pull, one optional notes file, one render.

## Final message format
One line:
`Client Desk <AGC|Splendor> (<Monday|Friday|now>): <the top line from push.txt>. <published and pushed | dry run, nothing published or pushed>.`
Add ` New desk page: <link>` or ` New report page: <link>` only when that page was published for the first time.
Add ` HELD: <what>` when step 5 held something.
