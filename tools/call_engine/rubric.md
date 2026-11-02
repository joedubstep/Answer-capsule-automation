# Call Engine rubric

The scorecard every sales-call review uses. The model reads this file, the evidence packet that
`tools/call_engine/review.py packet` prints, and the transcript. Python finds the evidence with timestamps
(`rules.py` ids in `code` below). The model makes the calls and writes them in plain words for Joey.

## Which source wins

1. **Locked Surven decisions and the live offer pages in Notion** (Surven offer MASTER, Packages,
   Close-Call Kit, Guarantee Conditions). Prices, guarantee numbers and links come from those pages at run
   time, never from this file.
2. **Joey's own watch notes** on the coach's 8/8 mastermind (LS Call Library). They outrank every other
   coaching document.
3. **The Lead Suite sales coach's call structure** (masterminds 6/10, 7/28, 8/8, 9/24, 10/1, 10/14, 10/28,
   and the offer-operators group).
4. **The Close-Call Kit steps.**

Where the coach and Surven's own rules disagree, Surven's rule wins:
- The coach's flow has no capacity screen. Surven's is required.
- The coach finances people who cannot pay. Surven never finances a home below break-even.
- Money is the coach's top objection because his buyers already clicked an ad. If money is the only thing
  that shows up on Joey's call, discovery did not go deep enough.

## How to grade, in this order

1. **The 3 questions first (Q1 to Q3).** Then the stages (S1 to S15). Then Joey's directives (J1).
2. Score each row `pass`, `partial`, `miss` or `n/a`, with a timestamp and one short line.
3. Python pre-scores the rows it can see (`auto_checks`). Confirm each one, or override it and say why.
   Regexes miss paraphrases, and Fathom speaker labels can be off by a line.
4. Pick the **3 fixes** that would have changed this call the most. Say each as one plain action, like
   "Ask how long the beds have been empty before you share the screen."
5. List up to 3 things Joey did well, with timestamps. Only real ones.

## Flags

- Python flags Joey's lines that match the table under "Banned on calls". Confirm or clear each one in
  `flags_review`. Each one goes on the page quoted word for word, with its timestamp link.
- If you hear one Python missed, add it to `extra_flags` with its id, the exact words and the timestamp.
- Clear a flag only when the words are not what the flag says, and write why. Cleared flags still show in
  the notes.
- Do **not** flag general market facts about speed (Joey, 8/12), and do not fault a price that differs
  from the kit. Joey prices by what is delivered. Note it, do not grade it.

## The 3 questions (Joey's review standard)

- **Q1. Was there a huge problem, said out loud by them?** Not Joey describing it. Them, in detail.
- **Q2. Do you know why they don't have it already?** The reason they never bought from anyone else is the
  objection you will get later. Find it in discovery, spend it at the close. Three buckets: logistical
  (money, location), fit, commitment (found something, stalled from fear). Most calls should land in
  commitment. If every call lands in money, discovery is too shallow.
- **Q3. Did you get a commitment to change?** The destination of every call is their commitment to a change
  that fits the offer.

## Stages

- **S1. Open.** No "is this a good time" (`good_time_ask`). 2 to 5 minutes of rapport (`rapport_minutes`).
  Set the frame: what will happen on the call and that it ends in a yes or a no (`agenda`).
- **S2. Problem.** Make them describe it in detail. Restate it sharper than they said it and get a yes.
  Binary questions ("is that X or Y?"). "When you say X, what does that look like?" (`problem_probe`).
  Bad answers kill calls: use the Three A's (agree, answer with context, ask again sharper).
- **S3. Timeline.** "How long has this been an issue?" Timelines win the close: what they said here is what you use at the price (`timeline`).
- **S4. What tried.** "What have you tried in that time?" "With getting X, can you do it with what you are
  doing now?" (`tried`).
- **S5. Cost.** "If nothing changes, what does that cost you?" Use their rent and their empty beds
  (`cost`, `rent`, `empty_beds`).
- **S6. Three layers.** What they want, what they are doing now, why it has not changed. The third layer is
  always internal. Why now? (`why_now`).
- **S7. Goal.** "Is that the humble goal or the actual goal?" What help do they want besides the result?
  (`goal`, `humble_vs_actual`).
- **S8. Capacity screen.** "If five more families toured next month, could you staff them?" Required before
  any resident (move-in) promise (`capacity`).
- **S9. Commitment before the pitch.** Stacked summary that ends "unless I'm missing something", then a
  yes to change. 1 to 10 check: under 8 means the pitch missed their problem; go back to why they came, not
  to price (`commitment`).
- **S10. Decision maker, before the pitch.** "Anyone else who would want to be in the know?" A partner is a
  logistical objection; find out early what kind of partner and how involved (`decision_maker`).
- **S11. Pitch.** Gate the screen share ("if it all makes sense, all I ask is a yes or a no today. Fair?").
  Tailor every line to their words. Tie down with "Ya?" or "Make any sense?", not "Any questions?"
  (`screen_share`, `tie_down`, `any_questions`, `transition`).
- **S12. Price.** After the problem and the yes to change (`first_price` after `commitment` and
  `timeline`). Their numbers first (placement fee times residents, or empty beds times rent), price last.
  After the price, stop talking. Option close on payment terms (paid in full or split), never on tiers.
- **S13. Objections.** Validate first, every time ("Ya, absolutely, that's normal") (`validate`). Smoke
  screens: "check my finances" (you can check on your phone, I'm not going anywhere), "send me a PDF"
  (what would you look for in it?). Partner ladder: what kind of partner, how involved, is it something you
  have to do or feel you should do. Two or more logistical objections stacked: bundle them into the
  refundable deposit (`deposit`). Emotional objections: go for the full close. Financing only after the
  break-even screen (`financing`).
- **S14. Offer rules.** See below. Tier prescribed, guarantee matches the tier, deadline true
  (`guarantee`, `urgency`, `scarcity`).
- **S15. Close and next step.** Ask for payment or the deposit on the call (`payment_close`, `deposit`).
  After a yes: payment in the call chat, onboarding booked and accepted on screen, support invite sent, all
  on the call. Never end without the next call booked with a day and time (`next_step`).

## J1. Joey's own directives

- Talk less. Before the pitch the prospect should have most of the words (`host_share_before_pitch`).
- No long monologues; watch anything over 90 seconds (`host_monologues_over_90s`).
- At the close: ask, then stop. Joey talks himself out of the closing moment (`host_share_after_price`).
- Speak faster, louder, with more tone. Pace is a rough proxy (`host_words_per_minute`).

## Offer rules (S14 and call prep)

- **Tier is prescribed, not chosen.** The ads promise the premium result; on the call, advise down. The
  option close is payment terms only. Rules are in `offer_rules.json`; live numbers are in Notion.
- **Downsell by asking, not asserting:** "That plan needs a daily ad budget. Is that something you can
  do?" Kit downsells: call support to text support, 5 ads to 3 ads.
- **Guarantee by tier.** The real product guarantees **tours** (the "Dollar Menu" guarantee: tours in 90
  days or Surven works free and pays the ad spend until it hits). A **resident** (move-in) number is only a
  headline, only with 8 or more empty beds and the staff to take them, and they still get advised down to
  tours. Sell the process, not the guarantee; a buyer who buys the guarantee has not decided it will work.
- **Deposit.** The refundable deposit link is in the Close-Call Kit. Use it for a logistical stack. Never
  make up an amount on the call. The trial is never called a deposit.
- **Deadline.** Any deadline said on the call must match `campaign.price_raise_deadline_et` in
  `config/surven.json` (`deadline_mismatch`; the day after, when the price goes up, is fine too). If the
  Close-Call Kit shows a different date than config, config wins and the review says so.
- **Placement agents:** never tell an owner to drop them (`cancel_placement`). Keep them; stop being only
  dependent on them.
- **Scope:** assisted living, memory care, board and care, independent living are in. Skilled nursing and
  recovery or sober housing are out: route out on the qualifying answer, do not rebuild the prospect.

## Banned on calls (flag ids)

| id | severity | what |
|---|---|---|
| `good_time_ask` | high | "is now a good time" |
| `deadline_mismatch` | high | a deadline day that is not `campaign.price_raise_deadline_et` |
| `cancel_placement` | high | telling them to drop placement agents |
| `banned_name` | medium | "death spiral", "virtual front desk", "chargeback" |
| `patients` | medium | say residents |
| `financing` | medium | financing before the break-even screen |
| `leads_for_families` | low | say families |

Copy rules (dashes, buzzwords, no price in writing, and so on) apply to the follow-up email through the
copy checker, not to what Joey says out loud.

## The follow-up email (sales calls)

- Joey's voice: short plain sentences, 4th-grade words, US English, no dashes, no emojis, state it and stop.
- What it holds: one line recap in their words, what Joey owes and when, the agreed next step. Nothing else.
- No price, never "patients" or "care home". Under 150 words.
  Signed `Joey` on its own line.
- It must pass `python3 -m tools.copy_check.check --context prospect_email`. `review.py render` runs it.
- Skip it (`skip_email` with the reason) when Gmail shows Joey already followed up after the call.

## Coaching calls

No scorecard. Five takeaways, each one plain action Joey can use on his next call, each under 30 words,
plus 1 to 4 timestamps worth a listen.

## Reminder and objection ids used by call prep

Prep picks the 3 reminders and up to 3 objections that fit the person (`prep.py pick`). Text lives in
`rules.py`; ids:
- Reminders: W1 (the 3 questions), W2 (ask then stop), W3 (faster, louder), W5 (timelines), W6 (extend the
  agents), W7 (decision maker early), W8 (capacity screen), W9 (why they never bought), W10 (downsell by
  asking), W11 (problem before the doc), W12 (validate first), W13 (numbers, no hype), W14 (route out fast),
  W15 (book the next call).
- Objections to expect: O1 (placement agents), O2 (partner), O3 (think about it), O4 (can't afford ads),
  O5 (burned by an agency), O6 (who else have you done this for), O7 (send me a PDF), O8 (short staffed),
  O9 (pay before move-ins), O10 (too far).

## Moves and objection candidates Python looks for

Moves: `agenda`, `discovery_open`, `problem_probe`, `timeline`, `tried`, `cost`, `why_now`, `goal`,
`humble_vs_actual`, `commitment`, `decision_maker`, `capacity`, `empty_beds`, `rent`, `placement`,
`screen_share`, `guarantee`, `urgency`, `scarcity`, `deposit`, `payment_close`, `tie_down`, `any_questions`,
`next_step`, `transition`, `validate`, `price_ask`.

Objection candidates (their lines): `money`, `partner`, `think`, `send_info`, `burned`, `proof`, `staffing`,
`terms`, `already_have`, `location`. Each comes with Joey's next line so the review can judge the handling.
