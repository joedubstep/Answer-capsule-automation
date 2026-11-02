---
name: inbox_desk
description: Inbox Desk, Joey's twice-a-day inbox triage. It sorts new Gmail (cold email replies, Google Voice texts, client, coach, vendor and data-sale mail), writes Gmail DRAFT replies in Joey's voice (with the one-page plan PDF attached when a home asked for it), saves coach takeaways to the Learnings database in Notion, flags opt-outs that still need a GHL cleanup, and sends Joey one short digest email. Use it on the schedule (weekdays 8am and 4pm ET), when asked "inbox desk now", "inbox desk backlog" (every unanswered cold email reply since 9/23), or "inbox desk dry run".
---

# Inbox Desk

## Purpose
Turn new mail into ready drafts and one short digest, so Joey stops checking his inbox and no cold email reply,
plan request or coach lesson sits unworked. Joey checks and sends every draft himself. Nothing goes to anyone else.

## Modes
- **Scheduled** (routine fire, weekdays 8am and 4pm ET): `start --mode scheduled`. New mail from the last 3 days
  that is not labeled `Desk/Done`, at most 25 threads. Every step below.
- **On demand** ("inbox desk now"): same as scheduled.
- **Backlog** ("inbox desk backlog"): `start --mode backlog`. Every cold email reply since 2026-09-23 with no answer
  from Joey yet (no reply in the thread, no draft waiting, and in the Surven HQ environment no email, text or call
  in GoHighLevel after it). At most 40 threads per run; run it again for more.
- **Dry run** ("inbox desk dry run", or a build session): add `--dry-run` to step 1. Do every read and every Python
  step. Do NOT create the label, drafts, Notion rows or Drive files, do NOT apply labels and do NOT send the digest.
  Say what would have happened.

## Inputs
- Gmail (connector): searches, threads, drafts, labels, and one email to Joey.
- Notion (connector): the Learnings data source (`config notion.learnings_ds`), the Answer Bank page
  (`notion.answer_bank`) and the private senders page (`notion.inbox_desk_settings`, optional).
- Google Drive (connector, optional): a copy of each plan PDF.
- Surven HQ GoHighLevel, read-only, through `shared/ghl.py` (only in the Surven HQ environment).
- `tools/inbox_desk/templates.md` (reply patterns), `tools/inbox_desk/plan_steps.json` (the plan's words),
  `config/surven.json` (`cold_email_domains`, `google.joey_gmail`, `inbox_desk.booking_link`).

## Steps
Run every command from the repo root (`/home/user/aca` in a routine). Working files live in `/tmp/inbox_desk/`.
Never print, echo or look for an API key.

1. **Start.** `python3 -m tools.inbox_desk.desk start --mode scheduled` (or `--mode backlog`; add `--dry-run` in a
   dry run). It prints the Gmail searches. If it prints `WARNING: no booking link`, carry on: drafts that need the
   link will be held and the digest says so.
2. **Private senders** (only when `notion.inbox_desk_settings` is set in config; `start` prints the page id).
   Fetch that Notion page, Write its text to `/tmp/inbox_desk/settings.md`, then run
   `python3 -m tools.inbox_desk.settings --from-text /tmp/inbox_desk/settings.md`. It holds the people who write from
   personal addresses (a coach, a client). Never copy those addresses anywhere else.
3. **Label.** `list_labels`. Find `Desk/Done` and keep its id. If it is missing: create it once with `create_label`
   (displayName `Desk/Done`). In a dry run, do not create it.
4. **Search.** Run each printed search with `search_threads` (`view: THREAD_VIEW_SUMMARY`, `pageSize: 50`). Write
   each raw result, exactly as returned, to `/tmp/inbox_desk/search/<name>-<page>.json` (an empty result `{}` is
   fine to save as `{}`). In backlog mode follow `nextPageToken` up to the page count shown. Then `list_drafts` with
   the query `start` printed (`pageSize: 50`) and Write ONLY the `threadId` values, as a JSON list, to
   `/tmp/inbox_desk/drafts_existing.json` (`[]` when there are none). The summary view has no
   dates or labels; that is expected, Python does not need them.
5. **Triage.** `python3 -m tools.inbox_desk.desk triage --done-label-id <the Desk/Done id>`.
   - `NOTHING NEW`: stop. Final message: `Inbox Desk (<when>): nothing new.` No digest.
   - Otherwise it lists the threads to READ. Python already sorted them; do not re-sort or second-guess them.
6. **Read.** For each READ id: `get_thread` with `messageFormat: PLAIN_TEXT`, and Write it to
   `/tmp/inbox_desk/threads/<id>.json`, trimmed so the run stays cheap: keep the thread `id` and `messageCount`,
   and for every message `id`, `sender`, `toRecipients`, `ccRecipients`, `subject`, `date` and `labelIds`. Keep
   `plaintextBody` only on the newest message from someone other than Joey, cut to its first 4,000 characters
   (keep the JSON valid). Copy the values exactly. For a coach email, read the full text from the tool result when
   you write its Learnings row.
7. **Classify.** `python3 -m tools.inbox_desk.desk classify`. It prints each item with its action. Do not open
   `work.json` unless you need one item's details.
8. **GoHighLevel context.** `python3 -m tools.inbox_desk.ghl_context`. Read-only. In the Surven HQ environment it
   adds the E code, the Email Pipeline stage, whether Joey already talked to them or answered in GoHighLevel, and
   a cleanup line for opt-outs that still have a code or an open deal. Anywhere else it prints `skipped`: carry on.
9. **Skeletons.** `python3 -m tools.inbox_desk.desk skeletons`. It writes `/tmp/inbox_desk/drafts/<id>.txt` from
   templates.md for every reply, and `/tmp/inbox_desk/plans/<id>.facts.json` for every plan.
10. **Your judgment, per item** (this is the only writing you do). Read `tools/inbox_desk/templates.md` once.
    - **draft_reply, cold reply**: edit `drafts/<id>.txt` so it is true for this one reply, using the template's
      "Make it theirs" notes and only facts from what they wrote. Change as little as you can. `confidence low`
      means read their words: if the sub-class is wrong, rewrite from the right section of templates.md.
      Never add a price or a second question.
    - **draft_plan** (they asked for the plan): confirm the home in at most 3 web lookups (WebSearch, WebFetch):
      the state license record or the home's own site. Fill `plans/<id>.facts.json` with only what that page shows,
      each with its URL: `home`, `city`, `state`, `beds {value, source}`, `care_type {value, source}`. Leave out
      anything you did not see on such a page; directory sites are dropped anyway. Then run
      `python3 -m tools.inbox_desk.plan --facts /tmp/inbox_desk/plans/<id>.facts.json --out-dir /tmp/inbox_desk/plans/<id>`.
      Exit 1 means the copy checker held a word you supplied (usually the care type): reword it and run it again.
      Never edit plan_steps.json or templates.md during a run.
    - **draft_reply, google_voice_text**: write the text reply (under 160 characters) in `drafts/<id>.txt`. Sending
      the draft texts them back from Joey's Google Voice number. Texts from Joey's own lines never get a draft.
    - **draft_reply, client**: answer what they asked, in Joey's voice (templates.md "client"). When
      `reply: copy_to_ghl`, the draft gets NO To line; Joey copies it into GoHighLevel.
    - **Summary line** (client mail and Google Voice texts always, any other draft when it helps): when you record
      the draft in step 12, add `--note "<one plain line: what they asked>"`. It goes in Joey's digest, which already names the sender, so
      do not repeat the name (for someone new, say who they are).
      No phone numbers or email addresses in the note.
    - **draft_reply, vendor_or_data_sale**: fetch the Answer Bank page once per run and answer from it. Anything
      marked "(verify)" there is never sent as fact: leave it out and record it as a need (below).
    - **learning** (coach mail): if it teaches something Joey can use (not a promo, a reminder or a calendar note),
      create one row in the Learnings data source (`notion-create-pages`, parent `data_source_id` from
      `config notion.learnings_ds` without the `collection://` prefix). Start from the `learning row` that step 7
      printed (Title, Source, Date, Link, Applied "__NO__") and add: **Summary** (up to 5 short plain bullets), **Key lines**
      (2 to 4 lines quoted word for word), **Apply to** (one or more of JP delivery, Offer, Sales calls, Campaigns,
      Ads, Ops). Then `desk result <id> learning_saved`. Nothing worth saving: `desk result <id> no_action`.
    - **summarize**: `desk result <id> summarized --note "<one plain line: what they want>"` (the digest already
      names the sender; for someone new, say who they are).
    - **flag** (opt-out): no draft. `desk result <id> no_action`.
11. **Check.** `python3 -m tools.inbox_desk.desk check`. Fix every BLOCK in the draft file (change only what the
    fix needs) and run it again until it exits 0. A draft you cannot fix: `desk result <id> failed --note "<why>"`.
12. **Drafts** (not in a dry run). For each checked draft, `create_draft` with the values step 9 printed:
    `replyToMessageId` = the item's `message_id`, `to` = [the item's `reply_to`] (leave `to` out when
    `reply_mode` is `copy_to_ghl`), `subject` = the item's `reply_subject`, `body` = the draft file's text (plain
    text). For a plan also pass `attachments: [{content: <the text of plans/<id>/plan.b64>, filename: <meta.json
    filename>, mimeType: <meta.json mime>}]`. Copy the base64 exactly. Then
    `desk result <thread id> drafted --draft-id <the draft id create_draft returned>` (`plan_drafted` for a plan). Optional: save the plan PDF to Google
    Drive (`create_file`, `base64Content` = plan.b64, `contentMimeType` application/pdf,
    `disableConversionToGoogleType` true, title "<home> plan <date>.pdf") and add its link to the result note.
    The reply quotes their email under the draft by itself; do not paste it in. Never send a draft: never call
    `send_message` with a `draftId`, and never call `send_message` for anyone but Joey.
    In a dry run, create nothing: record each checked draft as `desk result <thread id> drafted --draft-id dry-run`
    (`plan_drafted` for a plan) so the digest preview in step 14 shows what would have been drafted.
13. **Needs Joey.** For anything only Joey can decide (a call time they named, a new contact they pointed to, an
    Answer Bank "(verify)" item), add `--needs "<one plain line>"` to that item's `desk result`.
14. **Digest.** `python3 -m tools.inbox_desk.desk digest`. `NO DIGEST`: send nothing. `DRY RUN: do not send`:
    send nothing, show the digest in your reply. Otherwise `send_message` with `to` = [the `to` in
    `/tmp/inbox_desk/digest.json`], which is always `config google.joey_gmail`, and its `subject` and `body`
    exactly (no `draftId`, no attachments). One email, to Joey only.
15. **Labels**. `python3 -m tools.inbox_desk.desk labels`, then `label_thread` each printed id with the Desk/Done
    label id. `DRY RUN: do not label`: label nothing. Threads that were not read or failed are left unlabeled so
    the next run retries.

## What lands where
- **Gmail drafts** in each reply's own thread, waiting for Joey. Cold replies go back to the address they wrote
  from; the digest says which joey@<domain> address to send from. Plans carry the PDF.
- **Notion Learnings** (`notion.learnings_ds`): one row per coach lesson, Applied unchecked.
- **Google Drive** (optional): a copy of each plan PDF.
- **One digest email** to Joey only, only when something needs him: "Inbox Desk: 3 drafts ready (E24, E21,
  Maple House plan), 1 needs you".
- **The Desk/Done label** on every thread the desk finished.
- Working files in `/tmp/inbox_desk/` only. Nothing is written to GoHighLevel or to this repo.

## Hard rules
- Never message a prospect, client, family, partner or vendor. Drafts only. The digest goes to Joey only.
- GoHighLevel is read-only. Never tag, move or edit a record; the cleanup lines are for Joey to do by hand.
- Never print, echo or look for an API key.
- Every draft passes the copy checker (step 11) before it reaches Gmail. No dashes, no emojis, no price, no
  promises of results, one question of 2 to 5 words at most.
- Every fact about a home in a plan has a source link to a state record or the home's own site (plan.py enforces it).
- Never put names, emails, phone numbers or message text into the repo. Working files stay in `/tmp`.
- Keep it cheap: Python sorts, counts and checks. You read only the threads triage lists, and write only the words.

## Final message format
One line:
`Inbox Desk (<8am|4pm|now|backlog>): <N> drafts (<N> plans), <N> learnings, <N> need you. <digest sent | no digest | dry run, nothing written>.`
Add ` HELD: <n> draft(s) failed the copy check` when step 11 left any.
