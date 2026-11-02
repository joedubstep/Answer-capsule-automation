# HQ Desk

Your deal desk. Every morning it answers one question: who is closest to money today, what do you send or bring
them, and what is broken.

The follow-up planner still plans your calls and texts. The desk does not replace it. It sits on top and puts
the people who can pay you first.

## When it runs
6:00am Eastern, Monday to Saturday. It runs on its own in the Surven HQ cloud environment.

## Where you see it
One private page, the **HQ Desk**, made for your phone. The link is in `config/surven.json` under
`artifacts.hq_desk`. It updates in place every morning, so keep it pinned.

You also get **one short text**, but only when something is new and urgent:
- a new hot lead (they wrote in and you have not answered),
- a promise you owe now has a draft ready,
- a health flag just turned red (for example, nothing booked next week, or a routine failed).

No news means no text.

## What is on the page
1. **The top line.** For example: "3 owners to call today, 2 owed items ready, 0 calls booked next week".
2. **Health flags.** They turn red only when something is wrong:
   - discovery calls booked in the next 7 days (red at 0),
   - days since the last new lead (red at 7 or more),
   - email replies with no touch from you in 2 days or more,
   - days left until the price raise deadline (Nov 18 at 8pm each owner's own time; the date lives in the
     settings file, so it follows any change),
   - anyone who wrote in and got no answer for over 24 hours (replies you sent from Gmail do not show here),
   - any Surven routine whose last run failed.
3. **Up to 15 lead cards**, closest to money first. Each card has:
   - first name, home and code (tap the code to copy it, then text it to bridge a call),
   - why now and how many days they have waited,
   - the next step,
   - a ready text or email with a Copy button,
   - what you owe them, folded under the card, with a draft when one could be written. If it needs something
     only you have (a Loom, a number, a document), it says exactly what.

There are no phone numbers and no email addresses on the page.

## The groups, closest to money first
- **Hot:** wrote in during the last 3 days and nothing from you since.
- **Deciding:** met or heard the offer, no decision yet. Shows days since the meeting and whether they are on
  the price raise list.
- **Owed:** you promised something. Oldest first, with its age.
- **Rebook:** missed the meeting.
- **Replied, waiting:** answered a cold email, no touch from you in 2 days or more.
- **Warm referral:** still at New with no touch at all.

## What you do with it
1. Open the page with your coffee.
2. Work the cards top down. Copy a draft, read it, change anything, send it yourself.
3. Open "Owed" on a card, send what is drafted, or do the one thing it says is missing.
4. If a health flag is red, fix that first (for example, book calls).

Nothing is ever sent to a lead by this tool. Every draft has passed the copy checker first. If a draft broke one
of your copy rules, the page says it was held and does not show it.

## Time it saves
About 2 hours a week. About 10 minutes each morning of working out who matters most from the plan email, about
40 minutes a week of looking up and writing the answers you owe, and about 30 minutes a week of first drafts for
email replies. The bigger point is money: the owners who can pay you are at the top of one page every morning.

## Pause it
In claude.ai, open Routines, find "HQ Desk" and switch it off. Or ask Claude: "pause the HQ Desk routine".

## For builders
- Code: `tools/hq_desk/` (`pull.py` reads GoHighLevel, `score.py` sorts and flags, `drafts.py` checks drafts,
  `render.py` builds the page, `alert.py` decides the text, `run.py` runs it all).
- Runbook: `.claude/skills/hq_desk/SKILL.md`. Routine: `routines/hq_desk.md`.
- Tests (offline, synthetic data): `python3 -m unittest discover -s tools/hq_desk/tests -t .`
- Test run on AGC data (read-only, publishes nothing): `python3 -m tools.hq_desk.run --location agc --dry-run`
