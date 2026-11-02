# Time Ledger

Your 15-minute log, kept up for you. You keep writing the log the way you do now. Every night the Time Ledger
reads it, labels each action, estimates the minutes, and files it in Notion. On Sundays it tells you where the week
went.

## What it does
Each night at 11:45pm Eastern it:
1. Reads the "15 min log" sections at the bottom of your **Joey To-Do** page. It only reads. It never changes the
   page.
2. Splits each line into actions at every "/". "7:59 am/check email / approve the post" becomes two actions.
3. Fixes date mix-ups on its own, without touching the page. If you write today under yesterday's heading (two
   "15 min log 11/1" headings), it dates the top one to the right day and tells you. If you keep writing the next
   morning under the same heading, the new morning goes to its own day.
4. Labels each action with a role (CEO, Sales, Offer work, Marketing, Client delivery, CTO, Business development,
   Admin, Billing and finance, HR and hiring, Personal), a task, a kind (calls, offer, tools, distraction and so
   on) and whether it used AI. It learned this from about 400 of your labeled actions. When it is not sure,
   Claude decides.
5. Estimates minutes from your block times: a block runs until the next block, up to 30 minutes. If you wrote
   "for 15 minutes" or "until 12:04", it uses your number. "Stopped working" and "back 10:10" become a break.
6. Fills blank blocks ("437/", "1:32 pm /") with a guess from your Google Calendar, sent Gmail, Fathom
   recordings and GoHighLevel dials in that window. Every guess is marked **inferred**. Emails your own
   automations send to you do not count.
7. Adds only the new rows to the **15-Min Action Log** in Notion. Running it twice never adds a row twice. It
   looks back up to 3 days, so a block you fill in a day or two later still gets filed.

Every Sunday night it also writes a **weekly report**: a Notion page under Automations and the same report by
email to you. It shows:
- your hours by role, compared with the week before
- your selling time and its share of your work
- distraction minutes, and how many days in a row you stayed under 20 minutes
- your top 5 time sinks
- actions you did 3 or more times on 2 or more days (good things to hand to Claude)
- how many blocks were left blank
- 2 to 4 plain next steps

## Where you see it
- **Notion, 15-Min Action Log** (SURVEN HQ, Automations): one row per action. Columns: Action, Date, Block start,
  Minutes (est), Role, Task, Kind, AI, Confidence, Source (log or inferred), Key.
- **Notion, Automations:** a page each Sunday called "Time Ledger: week of Oct 26 to Nov 1".
- **Your Gmail:** the same weekly report, Sunday night.
- The nightly run ends with one line, like: "Time Ledger Nov 2: 13 actions, about 2.2 h of work; Sales 60 min,
  ...; distraction 21 min; 1 blank block(s)."

## What you do with it
- **Keep logging the same way.** Short is fine. A blank block is OK; it gets filled from your calendar when it can.
- **Sunday night or Monday morning:** read the email. Pick one repeated action from the list and ask Claude to
  automate it. Look at selling time and distraction first.
- **If a label is wrong:** change the Role (or Task, Kind, AI) in the Action Log row. Next week's report uses your
  fix. You never need to fill the database by hand.
- **If it says "Date fix":** you can rename the heading on the To-Do page. The rows are already dated right.

## What it saves
About 35 minutes a week: the log upkeep, moving and fixing the log, dashboard-accuracy prompts, "what did I do
yesterday" reconstruction, and the weekly "find what to automate" review (55 logged minutes went to log upkeep
alone in the first 10 days).

## How good the labels are
- Trained on 401 of your labeled actions. Cross-checked by holding out a fifth at a time: the role is right
  68% of the time (always guessing the most common role would be right 20% of the time).
- On your real log text, labeling each day with a model that had never seen that day: right 56% of the time
  overall, and 79% of the time on the rows it keeps for itself. Everything it is less sure of (about 6 in 10
  rows) goes to Claude to label.
- Minutes are estimates. On days you log every 15 to 30 minutes they land within about 1% to 7% of your real
  Wispr minutes (Oct 24 to 27: 1,151 estimated vs 1,159 real). On days with long stretches between entries they
  run low, because a block counts at most 30 minutes (Oct 28 to Nov 1: 658 estimated vs 1,672 real). Writing a
  line at least every 30 minutes keeps the numbers true.

## When it runs
11:45pm Eastern every night (the weekly report on Sundays). You can also open a Claude session on this repo and
say "run the time ledger", "backfill the time ledger" (every day on the page), "weekly time report", or add
"dry run" to see what it would do without writing anything.

## How to pause it
In claude.ai, open Routines, find "Time Ledger" and switch it off. Or ask Claude: "pause the Time Ledger routine".

## For builders
- Code: `parse.py` (page to rows), `classify.py` + `lexicon.py` + `model.json` (labels), `minutes.py`
  (estimates), `infer.py` + `ghl_calls.py` (blank blocks), `report.py` (daily and weekly), `run.py` (the stages
  the skill calls), `evaluate.py` (agreement with a labeled history).
- Notion SQL reads: the query tool returns at most 100 rows a call, even with a bigger LIMIT. Every SQL in
  `run.py` has a fixed ORDER BY (ending in the unique `url` column, or the GROUP BY columns) and is read in pages
  of `LIMIT 100 OFFSET 0, 100, 200 ...`. `run.py more <query>` counts each saved page, prints the next page's SQL
  while pages come back full, and joins the pages (once per url) after the first short page.
- Tests: `python3 -m unittest discover -s tools/time_ledger/tests -t .` (synthetic page in the same format as
  the real one; no real content).
- Retrain: `python3 -m tools.time_ledger.classify train --csv <labeled CSV outside the repo> --names <extra
  stoplist outside the repo>`. It ships only counts of tokens seen in 3 or more rows, drops anything written with
  a capital letter mid-sentence unless it is a known tool word, and refuses to write the model if the privacy
  check fails. Never commit the CSV or any action text.
- Check against a labeled history: `python3 -m tools.time_ledger.evaluate --page <fetched page> --csv <labeled
  CSV> --holdout` (prints aggregates only).
