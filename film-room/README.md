# Film Room

A single-page sales training room for an agency that fills empty beds at small care homes. It has four views:

- **Tape.** Every recorded sales call broken down: a timeline of objections, strong and weak moments and turning points, each linked to the exact second in the recording. It also shows what was said back and a better line to use next time.
- **Spar.** Role-play the call again against an AI version of the prospect, built from the real call: how they talk, what they object to, and facts they only reveal if you ask the right question. You can ask your corner for a hint mid-call. At the end, the call is graded against your own playbook's rubric, and graded reps are saved so you can track progress.
- **Proof.** One card per objection type. Each has the prospect's real words, what to say back, questions to ask next, and cited numbers you can say out loud, plus a searchable evidence library.
- **Math.** A screen-share calculator: what the empty beds cost, what 90 days of ads is likely to produce (with a 2,000-run simulation band), and how fast one move-in pays for the program. An inside view shows your margin and the odds of hitting the guarantee.

The page runs as a claude.ai Artifact. Sparring uses the Artifact runtime's `sample` capability (Claude inside the page, on the viewer's own account), and rep history uses the `db` capability. Everything else is static.

## Build

```sh
python3 build.py data/example dist/film-room.html
```

`build.py` merges the JSON files in a data folder into `template.html`. The data format is documented at the top of `build.py`. For the call breakdown shape, see `data/example/calls_example.json`.

## Private data stays out of this repo

This repository is public. Real call breakdowns, prospect names, the playbook, pricing and proof cards are private and must never be committed. Keep them in a folder outside the repo (or in `data/private/`, which is git-ignored) and build from there. `data/example/` holds only made-up data.
