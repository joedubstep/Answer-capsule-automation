---
name: copy_check
description: Check prospect or client copy against Joey's locked copy rules (dashes, US English, buzzwords, banned words, price, stats, invented results, merge fields, reading grade). Use when someone says "check this copy", "is this on brand", "run the copy checker", or before saving any draft a prospect or client will read. Also used to rebuild the Copy Checker page when the rules change.
---

# Copy Checker

## Purpose

One rules list (`tools/copy_check/rules.json`) that every Surven draft must pass before it lands anywhere.
This skill runs it on demand and reports the result in plain English.

## Modes

- **On demand** ("check this copy"): check the text the user gave and report. Nothing is written anywhere.
- **Dry run**: same as on demand. This skill never writes, sends or publishes during a check.
- **Rebuild the page**: only when asked, or during deploy, after `rules.json` changes. See step 7.
- **Scheduled**: none. There is no routine.

## Inputs

- The text: pasted in chat, a file path, or a draft another tool just wrote.
- Who reads it, as a context:

| Reader | Context |
|---|---|
| Cold email to an owner who is not a client yet | `prospect_email` |
| Cold text to an owner who is not a client yet | `prospect_sms` |
| A client (an owner Surven works for) | `client` |
| Joey only (briefs, notes, Notion pages for him) | `internal` |

  If it is not clear, ask once. If there is still no answer, use the strictest that fits: `prospect_email` for
  an email, `prospect_sms` for a text.
- Flags: `--require-link` when the message must carry the booking link; `--require-optout` for the first text
  to a new number; `--template` only for GoHighLevel templates that keep fields like `{{contact.first_name}}`.

## Steps

1. Work from the repo root (`cd /home/user/aca` in a routine, or the repo checkout in a session).
2. Write the text to a scratch file outside the repo, e.g. `/tmp/copy_check_input.txt`, with the Write tool.
   Never save real drafts, names or message text inside the repo. For an HTML email, write the plain text the
   reader sees (no tags). Include the subject line as the first line. A lowercase subject line on purpose
   (like "hey") shows as a "Lowercase start" note; that one is Joey's call.
3. Run:
   `python3 -m tools.copy_check.check --context <context> --file /tmp/copy_check_input.txt --json [--require-link] [--require-optout] [--template]`
   Exit 0 means no blocking issues. Exit 1 means at least one. Exit 2 means a bad argument or a checker error:
   report the error line and never treat the copy as passed.
4. Read the JSON: `ok`, `grade`, and `issues` (`rule`, `severity`, `match`, `line`, `fix`). `line` 0 means the
   whole text.
5. If `ok` is false:
   - For a draft you wrote: apply each blocking `fix` and run step 3 again until `ok` is true. Change only what
     the fix needs. Do not rewrite the rest. Stop after 3 rounds: if it still blocks (for example a dash inside a
     home's own name), say so in the report and do not save the draft as ready.
   - For Joey's own words: do not rewrite them. Report each blocking issue with its line and fix, and let him
     choose. Joey writes anything he says out loud (scripts, openers, videos), so never hand back a finished
     script.
6. Report to the user with the format below. Show warnings, never hide them, but keep them short.
7. Rebuild the page (only when asked or during deploy):
   - `python3 -m unittest discover -s tools/copy_check/tests -t .` must pass first.
   - `python3 -m tools.copy_check.build_page --out /tmp/copy_checker.html`
   - Read the artifact at `config/surven.json` key `artifacts.copy_checker` with the Artifact tool (action read),
     then publish `/tmp/copy_checker.html` to that same `url`. If the key is empty, stop and say the deploy step
     has not created the page yet. Never create a second page.

Other tools call it as a library instead of the command line:

```python
from tools.copy_check.check import check
result = check(text, "prospect_email", require_link=True)
if not result["ok"]:
    ...  # fix the blocking issues, then check again
```

## What lands where

- A check: the chat reply only. Nothing is saved, sent or published.
- A page rebuild: the one Copy Checker artifact named in `config/surven.json`.

## Hard rules

- Never send or post anything. The checker reads text and reports.
- Never put real drafts, names, phone numbers or emails into the repo. It is public.
- Never print, echo or look for an API key. This skill needs none.
- A blocking issue is never waved through. If Joey wants an exception (for example his own writing sample uses
  a dash), say so in the report and let him decide.
- Keep the report in plain US English with no em dashes.

## Final message format

First line: `Copy check: PASS` or `Copy check: FIX FIRST`, then `(N must fix, M to look at), reading grade G.`

Then, only if there are issues, one line each, most serious first:
`Line 3: "care home" -> Say assisted living, senior living, the community, or the home.`

After a page rebuild, one line: `Copy Checker page updated: <artifact url>`.
