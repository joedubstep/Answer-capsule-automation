---
name: call_engine
description: Surven sales Call Engine. "prep" builds Joey's call-prep page in Notion (inside Call Prep, his fixed format) for each sales, discovery or onboarding call today. "review" scores each new Fathom sales call against the rubric, adds a Sales Call Library row (Watched unchecked) with timestamped Listen-for links, and drafts the follow-up email in Gmail; coaching calls get 5 takeaways. Use it on the 6:30am ET weekday schedule (prep), the 9:30pm ET daily schedule (review), or on demand: "prep my calls", "prep tomorrow", "review <fathom link>", "backfill since 2026-10-01", or "dry run".
---

# Call Engine

## Purpose
Cut the hours Joey spends around each sales call: prep before, rewatching and note-taking after, and the
follow-up email and owed items that get missed. Python finds and counts; you judge and write.

## Modes
- **prep** (scheduled 6:30am ET Mon to Fri, or "prep my calls" / "prep tomorrow" / "prep <date>"): every
  step in Prep. One page per call inside Notion **Call Prep**. Calls that already have a page are skipped.
- **review** (scheduled 9:30pm ET daily, or "review my calls"): every step in Review, for new Fathom
  recordings after the newest one already in a call library, from the last 4 days, at most 3 per run.
- **review <fathom url>** (on demand): Review for that one recording, even if it is older.
- **backfill <YYYY-MM-DD>** (on demand): Review for every recording since that date, at most 10 per run
  (say "run it again" to continue; the final line says how many are waiting).
- **dry run** (add "dry run" to any mode): every step except creating Notion pages or rows, creating Gmail
  drafts, and texting Joey. Print what would have been created instead.

## Inputs
- `config/surven.json`: Notion ids (`notion.sales_call_library_ds`, `notion.ls_call_library_ds`,
  `notion.close_call_kit`, `notion.offer_master`), `google.surven_calendar`, `ghl.hq`,
  `campaign.price_raise_deadline_et`. Call Prep page id: `3bae1c3d79d88073b144dcaa5d17b758`.
- Connectors: Google Calendar, Notion, Gmail, Fathom. Surven HQ GoHighLevel (read-only, through
  `shared/ghl.py`) when this runs in the Surven HQ environment; elsewhere the GHL parts are skipped and the
  page says so.
- `tools/call_engine/rubric.md` (the scorecard) and `tools/call_engine/offer_rules.json` (tier rules).

## Step 0 (every mode)
Run everything from the repo root. Work files go to `/tmp/call_engine/` only.
```
rm -rf /tmp/call_engine && mkdir -p /tmp/call_engine
```
Check the connectors with ToolSearch: "calendar list_events" (prep only), "notion fetch", "notion create
pages", "gmail search_threads", "gmail create_draft", "fathom list_meetings". If any needed one is missing,
stop. Final message: `Call Engine: needs connectors <list>, add them in claude.ai Routines.`

## Prep
1. **Calendars.** Call the Calendar connector's `list_calendars` once (never assume the list). Then
   `list_events` for the target day (today in ET unless asked), `startTime` 00:00 and `endTime` 23:59 that
   day, `orderBy` startTime, on: `primary`, the Surven Calendar (`google.surven_calendar`), and the work
   calendar whose id ends in `@surven.ai` if it is listed (it only shows busy blocks). Write
   `/tmp/call_engine/gcal.json` as `{"primary": [...], "surven": [...], "work": [...]}`, keeping for each event only: `id`,
   `summary`, `status`, `start`, `end`, `attendees` (email, displayName, self, responseStatus),
   `description` (first 500 characters), `location`, `conferenceUrl`, `hangoutLink`.
2. **Existing prep pages.** Notion fetch `3bae1c3d79d88073b144dcaa5d17b758`. Write the `<page url="...">Title</page>`
   lines of its content to `/tmp/call_engine/call_prep_page.txt`.
3. **Match.**
   `python3 -m tools.call_engine.prep match --google /tmp/call_engine/gcal.json --ghl --existing /tmp/call_engine/call_prep_page.txt [--day YYYY-MM-DD]`
   It also reads the HQ GoHighLevel Discovery Call, Client Calls, Lead Suite and Joseph calendars, because
   GHL bookings show only as hidden busy blocks on Google. It prints the calls to prep, calls it left out
   (`not_prepped`, with the reason), and hidden busy blocks. If `not_prepped` has an outside meeting that
   you can tell is a sales call (for example a care-home owner booked through Calendly), say so in the final
   message; do not prep it automatically. If nothing is left to prep, go to step 9.
4. **Fathom list.** `list_meetings` with `created_after` 60 days ago, `max_pages` 6 (about 60 meetings;
   follow-ups and closes come within weeks of the first call). Save the text exactly as returned to
   `/tmp/call_engine/fathom_list.txt`.
5. **Gather.** `python3 -m tools.call_engine.prep gather --ghl --meetings /tmp/call_engine/fathom_list.txt`
   Then read `/tmp/call_engine/prep.json` only (never dump GHL yourself). Each call has `ghl` (contact, deal
   stage, last messages, notes), `prior_meetings`, `cold_email_reply`, `facts`, `signals`, `offer`,
   `reminders`, `expect`, and a `page` with default questions. If GHL gave a call its name, `gather` also
   re-checks Call Prep and moves the call to `skipped` when it already has a page.
   `prior_meetings` entries carry `match`: `email` or `full name` are sure; `first name` only means the
   Fathom title holds their first name ("Pat discovery"), so drop it unless its summary is about this home.
6. **Research each call (your judgment).** Budget per call: at most 3 web searches, 2 Gmail threads, 1
   Fathom summary.
   - **Offer check (once per run).** Notion fetch `notion.offer_master` and `notion.close_call_kit`. If they
     contradict `offer_rules.json` (tiers, guarantee type, deposit), the pages win: add a `sources` line
     "Offer page changed: <what>" so the rules file gets updated.
   - **Gmail.** `search_threads` with `from:<email> OR to:<email> newer_than:120d` (or the home name if there
     is no email). Read at most 2 threads with `messageFormat` PLAIN_TEXT. Their cold-email reply, if GHL did
     not have it: search the home name or their address together with `newer_than:60d`. Fill `gmail` as
     `[{"subject", "summary", "url"}]` and `cold_email_reply` as `{"date", "text"}` (their words, trimmed).
   - **Meet link.** If `call.meet_link` is empty, search Gmail for the booking confirmation
     (`<first name> newer_than:14d meet.google.com`) and put the link in `call.meet_link`.
   - **Earlier calls.** For the newest `prior_meetings` entry, read the Fathom summary (never a transcript
     here). If the Sales Call Library has a row for them (Notion SQL on `notion.sales_call_library_ds`,
     `WHERE "With" LIKE '%<first name>%'`, 3 rows max), read its `notes` for owed items and flags.
   - **Web facts.** Their website, the state licensing record, and their Google listing. Each fact is
     `{"fact": "...", "url": "<primary source>"}`. Anything you infer is `{"fact": "...", "inferred": true}`.
     Never put an unverified fact on the page as a fact.
   - **Facts and signals.** Set what you know in `facts` (`community_type`, `total_beds`, `empty_beds`,
     `uses_placement_agents`, `staffing_ok`, `can_fund_ads`, `operating`, `travel_nurse`,
     `below_break_even`, `rent`, `decision_makers`), leave unknowns as null. Add `signals` you have evidence
     for: `placement_agents`, `partner`, `burned`, `skeptic`, `trust_asker`, `send_info_asker`, `low_budget`,
     `small_home`, `many_empty` (8 or more empty), `staffing`, `rural`, `scope_risk`, `terms_asker`, and from
     an earlier call review `prior_invented`, `prior_no_timeline`, `prior_price_early`, `prior_no_next_step`,
     `objections_open`.
7. **Write each page** in `prep.json` under `page` (Joey's locked format, read live on the call, 2 to 3 words
   at a glance; shorter beats longer, one-word bullets are fine):
   - `qualifying`: 3 or 4 questions, tailored (beds and empty today, payer type, capacity, who else decides).
   - `suspect_pains`: 2 or 3, ultra short ("Agents slow", "Two rooms empty").
   - `timeline`: 2 or 3 must-ask (how long, what tried, one more).
   - `wants`: 2 or 3 dream outcomes in their words.
   - `other_notes`: buying words, decision makers, hard stops, their reply in a few words, anything owed
     from the last call. Python adds the tier line, the top objection to expect and up to 2 facts.
   - `callout`: the 3 do-different reminders that matter most for this person. Leave it empty to use
     `reminders` (picked from `rules.py` by the signals), or rewrite them shorter.
   - Questions and bullets only. Never a script or a finished line for Joey to say (he writes what he says).
8. **Render.** `python3 -m tools.call_engine.prep render`
   Fix every `must fix` line in `prep.json` and run it again (2 rounds at most; a page still failing is not
   written and the final line says so). `look at` lines are fine.
9. **Write the pages** (not in dry run). For each page in `/tmp/call_engine/pages/pages.json` with `ok`
   true: Notion create pages with parent `{"page_id": "3bae1c3d79d88073b144dcaa5d17b758"}`, `properties`
   `{"title": "<page_title>"}`, icon "📞", content = the text of its `md` file exactly. Then add `"<key>": "<new page url>"`
   to `/tmp/call_engine/created.json`. Never create a page anywhere but inside Call Prep.
10. **Finish.** `python3 -m tools.call_engine.prep finish [--dry-run]`
    If it prints `TEXT:` and this is not a dry run: `python3 -m shared.notify --file /tmp/call_engine/sms.txt`
    (works only in the Surven HQ environment; if it fails, add "text failed" to the final message).

## Review
1. **What is already logged.** Notion SQL (query data sources) on `notion.sales_call_library_ds`:
   `SELECT "Call", "Link", "Type", createdTime FROM "<ds>" ORDER BY createdTime DESC LIMIT 100`, and on
   `notion.ls_call_library_ds`: `SELECT "Call", "Link" FROM "<ds>" ORDER BY createdTime DESC LIMIT 200`.
   For **backfill** use `WHERE createdTime >= '<since date>'` with no LIMIT on both instead (a row for a call
   after that date cannot be older than the call), so no older row is missed.
   Write `/tmp/call_engine/library.json` as `{"sales": <results>, "ls": <results>}`. Rows whose Link is a
   share link or empty are matched by the date in their `Call` title plus a shared person's name or the same
   coaching word (mastermind, one-on-one ...), never by the date alone (see `meetings.py`).
2. **Fathom list.** `list_meetings` with `created_after` = 4 days ago (review), the backfill date (backfill),
   `max_pages` 3 (10 for backfill). Save the text exactly to `/tmp/call_engine/fathom_list.txt`.
3. **New recordings.**
   `python3 -m tools.call_engine.meetings new --list /tmp/call_engine/fathom_list.txt --library /tmp/call_engine/library.json > /tmp/call_engine/new.json`
   Backfill adds `--since <date> --max 10`. Read `new.json`.
   - `need_kind` lists recordings the title cannot place ("Impromptu Google Meet Meeting", "Joey g and X").
     Read each one's Fathom summary and decide: `discovery` (a home owner or operator, first sales talk),
     `follow-up` or `close` (a later sales talk), `coaching` (Joey being coached: his sales coach's
     masterminds, a 1:1 with his Lead Suite account manager, offer-operators groups), `onboarding` (a paying
     client), or `other` (vendors, data buyers, partners, personal). Write
     `/tmp/call_engine/kinds.json` as `{"<recording id>": "<kind>"}` and run step 3 again with `--kinds`.
   - If `todo` is empty, go to step 6.
   - **review <fathom url>** instead of steps 2 and 3: Fathom `get_recording_by_url` gives the recording id,
     title, date and url. If `library.json` already has that link, say so and stop (unless Joey said to
     review it again). Decide its kind as above and write `/tmp/call_engine/<id>/meeting.json` as
     `{"title", "date", "recording_id", "url", "kind", "type"}` (`type` is Discovery, Close, Follow-up or
     Coaching). In step 4b add `--meeting /tmp/call_engine/<id>/meeting.json`.
4. **Each recording in `todo`** (in order):
   a. Fathom `get_meeting_transcript` with `recording_id` and `url`. Save it to
      `/tmp/call_engine/<id>/transcript.txt`. If the tool result was saved to a file, copy that file. If
      not, write one line per turn as `[MM:SS] Speaker: text` (drop the link; copy every word exactly,
      never shorten).
   b. `python3 -m tools.call_engine.review packet --rid <id> --transcript /tmp/call_engine/<id>/transcript.txt`
      (add `--host "<Joey's speaker label>"` if the packet says the host was not found). Read what it prints.
      If it prints `NO TURNS`, the saved file was wrapped (for example in JSON): write the short form from
      step a and run b again.
   c. **Coaching call:** write `/tmp/call_engine/<id>/review.json` as
      `{"kind": "coaching", "with": "...", "takeaways": [5 lines], "listen_for": [{"ts", "label"}]}`. Each
      takeaway is one plain action Joey can use on his next call, under 30 words. Skip to e.
   d. **Sales call:** read `tools/call_engine/rubric.md` (once per run) and judge the call. Use the packet's
      flags, auto checks, promises and objection candidates as evidence, and check them against the
      transcript. Find their address first (the email bullet below says how), then Gmail `search_threads`
      for `to:<their email> after:<call date>` in sent mail: if Joey already followed up, set `skip_email`
      with the date. Write
      `/tmp/call_engine/<id>/review.json` exactly as the `tools/call_engine/review.py` docstring shows:
      - every rubric row scored, with a timestamp and one short line;
      - every top-severity flag `confirmed` or `cleared` with why (cleared only when the words are not a
        claim about Surven). Add any made-up client claim Python missed to `extra_flags`, word for word;
      - objections and how Joey handled them; owed items with real due dates (use the packet's default
        dates unless he named a day); the agreed next step; the 3 fixes; up to 3 real things done well;
        3 to 6 `listen_for` moments;
      - the follow-up email: recap in Joey's voice, what he owes and when, the agreed next step, signed
        `Joey`, under 150 words, no price, no statistics, no client stories. For a call more than 7 days old
        (backfill), write a short re-open note instead of a recap. Address, in this order: a Fathom invitee
        that is not Joey; `python3 -m tools.call_engine.review lookup --name "<their name>"` (Surven HQ
        GoHighLevel, read-only; pick the match whose company or date fits); Gmail `search_threads` for their
        name. Leave `to` empty if none is sure. If there is a Gmail thread with them, put its last message id
        in `reply_to_message_id`.
   e. `python3 -m tools.call_engine.review render --rid <id> [--dry-run]`. Fix every `must fix` line in
      review.json and run it again (2 rounds at most). The email must pass the copy checker
      (`prospect_email`); `look at` warnings go in the final message.
   f. **Write** (not in dry run):
      - sales call: Notion create pages with parent `{"data_source_id": <row.json parent.data_source_id>}`,
        `properties` = row.json `properties`, content = row.json `content`. Then Gmail `create_draft` from
        `draft.json` (`to`, `subject`, `body`, and `replyToMessageId` if present). Never send.
      - coaching call: Notion create pages from `ls_row.json` the same way. No email.
      - Record both in `/tmp/call_engine/created.json` as `{"<id>": {"row": "<page url>", "draft": "<draft id>"}}`.
5. Never open more than 3 transcripts in a scheduled run (10 in backfill). Leave the rest; the final line
   says how many are waiting.
6. **Finish.** `python3 -m tools.call_engine.review finish [--dry-run]`. If it prints `TEXT:` and this is
   not a dry run: `python3 -m shared.notify --file /tmp/call_engine/sms.txt`.

## What lands where
- **Prep:** one Notion page per call inside SURVEN HQ / Call Prep, titled "<Name> Call Prep <M/D>": Meet
  link, QUALIFYING, SUSPECT PAINS, TIMELINE, WANTS, OTHER NOTES, a red do-different box, and a folded
  "Sources and checks" list with every link. Optional text to Joey: "Call prep ready".
- **Review, sales call:** one row in the Sales Call Library (Type, With, Link, Listen for, notes, Watched
  unchecked); the page holds the scorecard with made-up client claims quoted at the top, the numbers,
  objections, what Joey owes with dates, the next step, the 3 fixes, and timestamped Listen-for links. One
  Gmail draft follow-up to the prospect. Optional text to Joey with owed items.
- **Review, coaching call:** one row in the LS Call Library (Type Coaching, Watched unchecked) with 5
  takeaways.
- Working files only in `/tmp/call_engine/`. Nothing about a prospect is ever written to this repo.

## Hard rules
- Never message a prospect, client, family or partner. Email is a Gmail DRAFT only; never send it.
- GoHighLevel is read-only. Never tag, move or edit a record, never write the planner's fields.
- Never print, echo or look for an API key.
- The follow-up email passes the copy checker as `prospect_email` before the draft is created
  (`review.py render` enforces it).
- Verify facts: every fact on a prep page has a primary-source link or is marked inferred.
- Joey writes what he says out loud: prep pages hold questions and bullets, never a script.
- No personal data in the repo; never paste a transcript, email or name into a repo file.
- Keep it cheap: Python counts and joins, you judge and write. Respect the per-run limits above.

## Final message format
One line, the one `finish` printed, plus anything that needs Joey: connectors missing, a held page or
draft, a likely sales call left out, copy-check warnings, or "text failed". Examples:
`Call Prep: 2 call(s), 2 page(s) written in Notion Call Prep. 10:00 AM Pat (Discovery); 2:00 PM Morgan (Onboarding).`
`Call Review: 1 sales call(s) reviewed, 1 row(s) added, 1 follow-up draft(s) in Gmail, 0 coaching takeaway(s). Pat Discovery: you owe PDF by Fri 10/30; 2 made-up client claim(s) flagged`
