# Lead List

Builds the next state's batch of homes for your cold email. Cold email is your only live lead source right now,
and the queue is running low, so this keeps it full.

## Why you need it
- The queue of homes cleared for email 1 runs out within weeks at the current sending pace, and faster once
  the senders ramp up. Run `python3 -m tools.lead_list.runway --data <state data folder>` for today's numbers.
- Until now, a new state took a long PC Claude session by hand: the license list, phones, emails, the copy for
  each home, then loading it. This tool does all of that in one run.
- Each 100 new homes with an email adds about half a day of sending at 140 a day (about a day at today's pace),
  because about 2 in 3 to 3 in 4 addresses pass the nightly mailbox check. So at the faster pace you will want a
  new state every few days.

## What it does
For one state at a time:
1. Reads the state's own license list (the file you or Claude download from the state's website).
2. Keeps only **assisted living homes with 40 or more licensed beds** and an active license (your rule since
   10/23).
3. Drops every home the campaign already has: same license number, same name and city, same phone, or same email.
4. Finds each home's own website, and only counts a site when the page shows the home's phone or street address.
5. Finds an email the home itself prints on its site (or the state list prints). It prefers the
   administrator's own address, then admissions or director, then info@. **It never guesses an address.**
6. Writes each home's 4 emails exactly like the rest of the queue: your locked v3 copy ("Hi Pat, how many rooms
   are open at Sunny Oaks right now?"), the day 7 email built at send time, half the homes on version A and half on
   version B. Every email passes the copy checker first.
7. Writes a review sheet with one row per home: kept or left out, why, and where each fact came from.

It never sends anything, never loads anything by itself, and never touches GoHighLevel.

## The first two states
- **Florida.** About 3,000 licensed assisted living homes. The campaign has only 230 of them. The state list
  gives beds, the administrator's name and often the website. Florida's site may refuse to export the whole state
  at once. Then Claude (or you, with a few clicks) exports it one county or area at a time into one folder, and
  the tool reads the whole folder.
- **North Carolina.** No NC homes in the campaign yet. Adult care homes (NC's assisted living license) often have
  40 to 120 beds.

More states (Michigan, Tennessee, Virginia, Washington, Arizona) are one small file each.

## When it runs
Only when you ask. There is no schedule. Say to a Claude session on your PC: **"build the next state list for
Florida"** (or any state it knows).

It must run on your PC, because the cloud sessions are not allowed to reach state websites or the homes' own
websites (tested Nov 2: every state site was refused). On your PC the web is open.

## Where the output lands
A folder per state, for example `lead_list_out\fl\`:
- `review.csv`: open it in Excel. One row per home, kept or left out, with the reason.
- `HOW-TO-LOAD.md`: the exact load steps for the Claude session.
- The three files the engine needs (queue, lead facts, prospects), ready to add.

## What you do with it
1. Claude tells you how many homes are ready, how many emails greet the person by first name, and about how
   many days of new homes it adds.
2. Glance at 10 rows of `review.csv`. Say "load it" or "skip it".
3. Claude loads it (about 5 minutes). That night the engine checks every mailbox. Only homes that pass get
   email 1, after every home already in the queue.

## Minutes it saves
Your time log has no entries for building state lists, so this is an estimate, not a measurement. By hand, a state
took about an hour of your time in a PC session (asking, checking, loading). With this tool it is about 10
minutes: say the state, read the counts, say "load it". At 140 new homes a day you need 2 or 3 states a week, so
it saves about 2 hours a week. The bigger win is money: cold email is your only live lead source, and this keeps it
from running dry. Ask "how much runway is left" any time and Claude answers from the live queue.

## How to pause it
Nothing to pause: it only runs when you ask. To undo a load before it is published, Claude copies the backups
back (the load step keeps them in the batch folder).
