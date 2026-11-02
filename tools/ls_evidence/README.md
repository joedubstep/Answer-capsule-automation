# Lead Suite Evidence

Your proof for the Lead Suite refund, on one page. Every Sunday morning it tells you where the refund case stands,
gives you the exact rows to type into the Lead Suite portal, and keeps the full proof for the refund file.

## Why it exists
Lead Suite only refunds the fee if you prove two things: every lead was worked with their scored checklist, and the
portal checklists are filled in. GoHighLevel already holds the proof (every call, text and email has a time stamp),
but the portal has no way to connect to it. So you type each row by hand. This page does the looking up for you.

## When it runs
6:00am Eastern every Sunday, before your "update LS portal" block. It runs on its own in the Surven HQ cloud
environment. You can also ask Claude any time: "lead suite evidence now".

## Where you see it
One private page, **Lead Suite Evidence**. The link is in `config/surven.json` under `artifacts.ls_evidence`. It
updates in place every Sunday, so keep it pinned. You get no text from it.

## What is on the page
1. **The scoreboard.** Qualified booked calls so far against the number in the contract, days left in the 90-day
   window (the August pause is skipped, as Lead Suite's CSM said), how many showed, and the share of checklist boxes
   done. Then one plain line: where the refund case stands.
2. **What GHL can prove, and what it cannot.** For example, GHL cannot prove the daily ad spend. That proof lives in
   Meta Ads Manager and the Meta charges on your Mercury card.
3. **Rows to enter in the portal.** Only the leads and calls you have not typed in yet. Each row shows the boxes in
   the same order as the portal, with Yes, No, Not due or Unknown. Tap Copy, paste, done. "Copy all" copies every row.
   - A lead row for "+ Add Lead": the 6 boxes (triple dial, SMS 1, double dial after a reply, SMS 2, SMS 3, replied).
   - A call row for "+ Add Call": the 5 boxes (triage call, show-rate SOP, pre-call email, morning confirm, showed)
     and the notes. The notes come from your GHL note on that call. If there is none, the row asks you to write 3 to
     5 sentences. It never makes notes up.
   - "Why each answer" under a row shows the time stamp behind every box.
   - A row marked **Check** means a GHL box you ticked does not match the call and text times. Look before you enter it.
   - A row marked **Changed** was on an earlier page, but an answer changed since (for example, the lead replied).
     Fix that row in the portal.
4. **Evidence for the refund file.** Every lead since ads went live and every booked call, with every box and its
   time stamp. "Copy lead table" and "Copy call table" paste straight into a sheet.

There are no phone numbers and no email addresses on the page. Each person is a first name and their reply code.

## What you do with it
1. Sunday morning, open the page.
2. Read the scoreboard line.
3. Copy each row into the portal. Fix any Changed rows. Look at any Check rows first.
4. Once a month, copy the two evidence tables into the refund file.

## What it needs from you
- Log each booked call's outcome in GHL (showed or no-show on the calendar, or move the deal) and leave a short note
  that starts with "OUTCOME:". The page reads both.
- Each row shows on the page once, the Sunday after it is finished. If you skip a Sunday, tell Claude
  "lead suite evidence now, entered through" and the last date you typed in. Every row after that date comes back.
  The evidence tables at the bottom always hold every row too.

## Time it saves
About 30 to 45 minutes a week: no more scrolling each lead's conversation to work out when the texts and dials went
out, and no more writing the call rows from memory. The bigger point is the refund: the proof is collected the same
way every week, with time stamps, before anyone asks for it.

## Pause it
In claude.ai, open Routines, find "LS Evidence" and switch it off. Or ask Claude: "pause the LS Evidence routine".

## For builders
- Code: `tools/ls_evidence/` (`pull.py` reads GoHighLevel, `score.py` works out every box, the scoreboard and which
  rows are new, `render.py` builds the page, `run.py` runs it all, `profile.py` finds the ids and fields).
- Rules and dates: `tools/ls_evidence/settings.json`, each block with its source.
- Runbook: `.claude/skills/ls_evidence/SKILL.md`. Routine: `routines/ls_evidence.md`.
- Tests (offline, synthetic data): `python3 -m unittest discover -s tools/ls_evidence/tests -t .`
- Test run on AGC data (read-only, publishes nothing): `python3 -m tools.ls_evidence.run --location agc --dry-run`
