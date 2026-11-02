# Copy Checker: no routine

- **Name:** Copy Checker
- **Schedule:** none. Do not create a routine for this tool.
- **Environment:** any. It needs no GoHighLevel key and no connectors.
- **Class:** A (no connectors), artifact only.
- **Artifact:** one private page, URL stored in `config/surven.json` at `artifacts.copy_checker`.

## Why there is no schedule

The checker only does work when there is text to check. Joey uses the page by hand, and every other tool runs
`python3 -m tools.copy_check.check` (or imports `check`) each time it writes a draft. A schedule would spend
credits and check nothing.

## Deploy step (once)

1. From the repo root: `python3 -m unittest discover -s tools/copy_check/tests -t .` must pass.
2. `python3 -m tools.copy_check.build_page --out /tmp/copy_checker.html`
3. Publish `/tmp/copy_checker.html` as a new private artifact with the icon `check` and the description
   "Paste a draft and see every place it breaks Surven's copy rules, with the fix."
4. Put the new URL in `config/surven.json` at `artifacts.copy_checker`.

## When the rules change

Run the three steps above again, but publish to the existing `artifacts.copy_checker` URL (read it first with
the Artifact tool, then publish with `url`). The skill's step 7 has the exact steps:
`.claude/skills/copy_check/SKILL.md`.
