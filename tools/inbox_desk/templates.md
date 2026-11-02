# Inbox Desk reply patterns

These are the starting point for every draft the Inbox Desk writes. Python fills `{greeting}`, `{home}` and
`{booking_link}` (`python3 -m tools.inbox_desk.desk skeletons`). The model then makes it true for this one reply
with real facts from what they wrote, and changes as little as it can.

## Voice rules (Joey's, locked)

- State it and stop. When a line explains or softens the line before it, delete it.
- Short plain sentences, 4th grade. US English. No dashes of any kind. No emojis. No exclamation marks.
- No filler at the start or end. Never "Thanks for writing back", "Fair question", "Great question" or "I hope
  this helps". A short acknowledgement is "Okay", never "Got it".
- Never repeat back what they just said ("Good to hear you're full", "Got it, 2 rooms"). Put their own word
  inside the next line instead ("filling the 2 open rooms at {home}").
- Their first name was already in Joey's first email, so a cold reply opens with no greeting and no name. Start
  with the point. Client and vendor mail keeps `{greeting}`.
- The ask is ONE question of 2 to 5 words. Never two questions.
- No price, no range, no number about cost. If they ask the price: "I'll give you a straight answer on a quick call."
- Name the situation, never the person. Take the blame, never give it ("I should have been clearer").
- "Residents", never "patients". "Families", never "leads". Never "care home" or "enquiry".
- Never "audit", "assessment", "grade" or "score". Never "is now a bad time".
- Never claim an outcome. Never say Surven calls their families (that depends on the plan they buy).
- The result phrase is "filling your empty beds", word for word. Never "fill your open rooms" or any other
  version of it.
- "I'd be willing to" goes in a thread once. When the email they answered already offered the plan (the item
  shows `offer: plan`), write "The one-page plan for {home} is still open. Want me to send it?" instead.
- Never confirm a call time as booked. Say the time works and that the invite will follow. Put
  "book <first name> <day> <time>" in the run results so the digest tells Joey to book it.
- Sign off with just `Joey`. No title, no slogan line.
- Every fact about their home comes from what they wrote or a page we checked. Never guess.

The book-a-call line is the booking link from `config/surven.json` (`inbox_desk.booking_link`). It is the same
link Joey's price-raise emails use. Never type a different link.

## vacancy_or_family_misread

They answered like a family asked for a room ("we have rooms available", "are you looking for memory care?",
"2", "as many as you want"). Clear it up in one line, say what Surven does, offer the plan.

```text
I should have been clearer. I'm not a family looking for a room.

Filling your empty beds is the only thing I do. We're not a placement agency. No move-in fee per resident.

I'd be willing to write up a one-page plan for filling the open rooms at {home}. Want me to send it?

You can also book a call here: {booking_link}

Joey
```

Make it theirs: if they named a number, use it ("filling the 2 open rooms at {home}"). If they asked about care
type or price as if Joey were a family, the first line already answers it. Do not answer the family questions.

## asked_for_plan

They said yes to the one-page plan. The plan PDF is attached to this draft (`python3 -m tools.inbox_desk.plan`).

```text
Here is the one-page plan for {home}. It's attached.

Want to walk through it?

You can book a time here: {booking_link}

Joey
```

## asked_for_plan_tool

They said yes to the day 7 email ("I built a free tool... Reply yes and I'll let you give it a try"). Same
attached plan, a different first line.

```text
Here is how it would work for {home}. It's one page and it's attached.

The first step is a short call. Want to pick a time?

You can book one here: {booking_link}

Joey
```

## question_what_is_this

They asked who Surven is, what this is about, or whether they have a contract with us. Answer it flat.

```text
I'm Joey, and I run Surven. Filling your empty beds is the only thing I do. We're not a placement agency. No move-in fee per resident.

I'd be willing to write up a one-page plan for {home}. Want me to send it?

You can also book a call here: {booking_link}

Joey
```

Make it theirs: "Do we have a contract?" gets "No, there's no contract." as a new first line. "I'll take a look"
(no question at all) also lands here with low confidence: they did not ask who Joey is, so cut the "I'm Joey, and
I run Surven." sentence and start with "Okay."

## interested_call

They asked to talk, gave a number or a time, or asked how it works or what it costs.

```text
Happy to talk. You can pick a time here: {booking_link}

Does this week work?

Joey
```

Make it theirs:
- They named a day and time: "{day} at {time} works on my end. You'll get the invite." Then "If that changes,
  you can pick a new time here: {booking_link}" and no question. Put "book <first name> <day> <time>" in the run
  results.
- They gave a number: "I'll call you at the number you sent." Never write the number into the draft.
- They asked the price: "I'll give you a straight answer on a quick call." Never a number.

## full

They are full or have no open rooms right now. Respect it in one line and stop.

```text
Okay, thank you.

If a room opens up, you can book a time here: {booking_link}

Joey
```

No draft for "not interested" (they said no to Surven, not to rooms) and none for opt-outs or auto-replies.

## wrong_person_or_referral

They said the person left, or that someone else handles this.

```text
Thank you. Who should I talk to?

Joey
```

Make it theirs: if they already named someone, write "Thank you. I'll reach out to {their first name}." and no
question. Put "new contact: <first name> at <home>" in the run results so the digest tells Joey. Never email the
new person from here.

## google_voice

A text to Joey's Google Voice number from someone who is not one of his own business lines. Sending the draft
texts them back from Joey's number. Keep it under 160 characters, one question at most, no link unless they
asked for one.

```text
Hi, it's Joey. {answer in one short sentence}
```

Texts from Joey's own lines (Surven GHL, the AGC line, the Splendor line) never get a draft. They are his own
tests or agent replies. The digest lists them only when one looks like a real family (then Joey answers in GHL).

## client

Mail from a client home (AGC, Splendor, the legacy client) or a partner writing to a client home. Answer what they asked,
in Joey's voice, as the person who runs their marketing. AGC partner mail comes through the GoHighLevel relay
(mg.americangoldencare.com): that draft has NO To line. Joey copies it into the AGC conversation in GoHighLevel.

```text
{greeting}

{the answer, 1 to 3 short sentences}

Joey
```

## vendor

Data buyers and vendors (SimpleClosure, Polyshares, DataVendor, Mercor, Labelbox, Sell Traces). Answer from the
Answer Bank page (config `notion.answer_bank`): copy the Short answer, delete the [source] brackets. Anything the
Answer Bank marks "(verify)" is never sent as fact: leave it out and add "needs you: <what to check>" to the run
results. Never agree to a price, a deal, a call time or a signature.

```text
{greeting}

{the answer from the Answer Bank}

Joey
```
