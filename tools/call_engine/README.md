# Call Engine

Your sales call helper. It does the work before and after every sales call so you only do the call.

- **Before the call (prep):** a one-screen prep page in Notion, in your locked format, ready when you wake up.
- **After the call (review):** a scorecard of how the call went, a row in your Sales Call Library, and a
  follow-up email waiting in your Gmail drafts.

## When it runs
- **Prep:** 6:30am Eastern, Monday to Friday. It looks at today's calls only.
- **Review:** 9:30pm Eastern, every day. It looks at Fathom recordings from the last few days that are not
  in your call libraries yet.
- **Any time you ask:** open a Claude session on this repo and say "prep my calls", "prep tomorrow",
  "review" plus a Fathom link, or "backfill since 2026-10-01". Add "dry run" to see what it would do without
  writing anything.

## Where you see it
**Prep page** (Notion, SURVEN HQ, inside **Call Prep**, one page per call, named like "Pat Example Call
Prep 11/3"):
1. Meet link at the top, with the time and the kind of call.
2. QUALIFYING, SUSPECT PAINS, TIMELINE, WANTS, OTHER NOTES: short bullets you can read at a glance.
3. OTHER NOTES also says which offer the rules point to and why, the objection most likely to come up, and
   up to 2 facts about the home, each with a link to where it came from.
4. A red box: the 3 things to do differently with this person, picked from your own watch notes.
5. A folded "Sources and checks" list at the bottom: every link, their cold-email reply, earlier calls,
   the deal stage in GoHighLevel, and the questions the offer rules say to ask.

It covers discovery, sales, follow-up, close and onboarding calls. It skips coaching calls, time blocks,
and any call that already has a prep page.

**Review** (after each sales call):
- A new row in the **Sales Call Library** with Type, With, the Fathom link, "Listen for" timestamps and a
  one-line note. **Watched** stays unchecked for you.
- Inside the row, the scorecard:
  - Your 3 questions: was there a huge problem, do you know why they don't have it already, did you get a
    commitment to change.
  - Each step of the call from your coach's structure and your own watch notes, marked Pass, Partial or Miss
    with a timestamp.
  - The numbers: how much of the talking you did, your longest stretch, how many questions you asked, when
    price first came up.
  - Flagged lines (like asking if it is a good time), quoted word for word with a link to that second.
  - Their objections and how you handled them.
  - **You owe:** every promise you made, with a due date.
  - The next step, the 3 fixes for next time, and what you did well.
  - Listen for: tap a timestamp and Fathom opens at that second.
- A **Gmail draft** to the prospect: a short recap in your voice, what you owe and when, and the next step.
  It has already passed the copy checker. It is never sent for you.
- Coaching calls (your coach's masterminds, 1:1s with your account manager) get a row in the **LS Call
  Library** with 5 takeaways instead.

You may also get one short text after each run, only when there is something to look at: "Call prep ready"
in the morning, or "Call review ready ... you owe ..." at night.

## What you do with it
- **Morning:** open the prep page before the call. Skim the red box. Keep it open during the call.
- **Night:** open the Gmail draft, read it, change anything, and send it. Do what is under "You owe" by the
  date. Open the row, read the 3 fixes, and listen to the timestamps instead of rewatching
  the whole call. Check Watched when you are done.

## Minutes it saves
About 110 minutes a week at 2 sales calls a week. The Oct 29 call took about 4 hours around a 24 minute
call: 80 minutes of prep, a 55 minute rewatch with notes, 87 minutes of framework study and 22 minutes of
rule edits. Now prep is about 5 minutes of reading, the review is about 10 minutes of listening to the
flagged moments, and the follow-up email is a 1 minute read. It also stops owed items and follow-ups from
slipping, and it fills the Sales Call Library, which had 1 row while 13 discovery calls happened in October.

## Good to know
- It reads Google Calendar, Notion, Gmail, Fathom and your Surven HQ GoHighLevel. It never changes anything
  in GoHighLevel and never emails anyone. The only things it creates are Notion pages and rows, Gmail
  drafts, and texts to you.
- Discovery calls booked through GoHighLevel only show as a private busy block on Google, so prep reads the
  GoHighLevel calendars too. If it sees a busy block it cannot read, the morning message tells you the time.
- Fathom sometimes puts the first words of a line under the wrong speaker. Listen to a flagged moment before
  you act on it.
- If a call cannot be reviewed one night, the next night tries it again, for up to 4 days. After that, say
  "backfill since" and the date. The night message says when a call was held or more are waiting.
- If a Gmail draft has no "To" address, the tool could not find their email for sure. Add it before you send.
- Prices are never stored in this tool. It reads the live Surven offer page and Close-Call Kit each run. If
  they change, the prep page says so.
- To change what the scorecard checks, open a Claude session on this repo and say what you want, like "add
  a check for the deposit link". The rules live in `rubric.md` and `rules.py`.

## How to pause it
In claude.ai, open Routines, find "Call Engine Prep" or "Call Engine Review" and switch it off. Or ask
Claude: "pause the Call Engine routines". You can still run it by hand any time.
