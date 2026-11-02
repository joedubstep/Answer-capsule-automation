# Copy Checker

## What it does

It reads any email or text. It shows every place the draft breaks your copy rules, with the fix next to it.

It catches the things you used to fix by hand:

- em and en dashes, and hyphens used as dashes
- British spellings and words (US English only)
- buzzwords, idioms and metaphors (ROI is fine)
- "care home", "patients", and "leads" when you mean families
- audit, assessment, grade or score in cold outreach
- "is now a bad time" and "when is a good time to talk"
- a price before the call
- emojis, needy lines ("just checking in"), filler and hype
- names that were never filled in, like {first} or [Name]
- sentences that start lowercase, sentences over 20 words, and more than one question in a text
- the reading grade (aim for 4 to 6)

Red means fix it before it goes out. Yellow means take a look and decide.

## Where you use it

**1. The Copy Checker page.** Open the link on your phone or laptop. Paste a draft. Tap who it is for: Cold email, Cold text, Client or Internal. Every problem is marked in your text. The list below says what is wrong and how to fix it. The reading grade sits at the top.

Three boxes you can tick:

- **Needs booking link**: turns red if the booking link is missing.
- **First text (needs STOP line)**: turns red if there is no "Reply STOP to opt out" line.
- **Template (merge fields OK)**: lets GoHighLevel fields like {{contact.first_name}} through. Leave it off for a finished draft.

**2. Inside every other tool.** Every draft a Surven tool writes for a prospect or a client goes through these same rules. That happens before it reaches your Gmail drafts, Notion or a page. Red problems get fixed before you see the draft. Yellow ones show up next to it.

The page and the tools use one rules list, so they always agree.

## When it runs

There is no schedule. The page is always there. The other tools run it every time they write a draft.

## What you do with it

Paste, fix the red, decide on the yellow, then tap Copy text and send it the way you normally do. It never sends anything itself.

## Minutes saved

About 45 minutes a week. That is the time spent reading drafts line by line for dashes, spellings, banned words, lowercase starts, the booking link and the opt-out line.

It also stops the kind of mistakes that got through before. Dashes were in 8 of 12 templates. A British spelling reached a care-home email.

## Good to know

- A capitalized word in the middle of a sentence is treated as a name. So a home called "Empower Pines Living" does not get flagged as a buzzword. A word at the start of a sentence, a line or a bullet is always checked.
- "Lead" as a job title (lead caregiver, lead nurse) and "leads" as in "she leads the front desk" are fine. "Leads" meaning families is not.
- "Care Home" with capitals gets a yellow note, because it is often part of a home's name.
- It does not check facts, tone or whether a link opens. You still read every draft.

## How to change or pause it

To add or drop a word or a rule, open a Claude session on this repo. Say what you want, like "add the word synergy to the copy rules". Claude changes the rules list, runs the tests and updates the page.

There is nothing to pause. It only runs when you open the page or another tool writes a draft.
