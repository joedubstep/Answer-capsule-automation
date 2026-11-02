---
name: lead_list
description: Lead List. Builds the next state's batch of 40+ bed assisted living homes for Surven's cold-email engine from the state's own license list (dedupe against the campaign, the home's own website, a published email, v3 copy with A/B), then loads it on Joey's OK. Use when asked to "build the next state list for <STATE>", "the queue is running low", "how much runway is left", or to load a batch that was already built. On demand only; needs a session with the open web (Joey's PC).
---

# Lead List

## Purpose
Keep the cold-email queue full. One run turns a state's license list into ready queue entries in the engine's
exact format, with a review sheet, and loads them only after Joey says yes.

## Modes
- **On demand** ("build the next state list for Florida"): steps 1 to 9. Load (step 9) only after Joey's OK.
- **Dry run** ("dry run", "just show me"): steps 1 to 8. Never step 9.
- **Runway only** ("how much runway is left"): step 2 only.
- There is no scheduled mode. Do not create a routine for this tool.

## Inputs
- This repo (public): `C:\dev\aca` on Joey's PC. Run every command from its root. On Windows use `python`,
  elsewhere `python3`. A cloud session can only run the tests: the state sites are blocked there and the engine's
  state repo is private, so it has no `<DATA>`.
- The engine's state folder, freshly pulled, read-only for steps 1 to 8: `C:\dev\surven-outreach\data\carehome`
  on the PC (after `python tools/cloud_state.py pull` in `C:\dev\surven-outreach`). Call it `<DATA>` below.
- An output folder outside both repos, e.g. `C:\dev\lead_list_out`. Call it `<OUT>`. The batch lands in
  `<OUT>\<st>\`.
- The state's license file, or a folder of them (step 3). Call it `<FILE>`.

## Steps
1. **Can this session reach the web?** `python -m tools.lead_list.run find-download --state <st>`
   - Exit 3 (`BLOCKED`) means this session's network refuses state sites. Stop. Final message:
     `Lead List: this session cannot reach state websites. Run it in a Claude session on Joey's PC.`
   - `no data file links found` is normal for a state whose list comes from a search form (Florida). Go on.
   - If `<st>` has no module (`run sources` lists them), go to step 1b first.
1b. **New state module** (judgment). Use WebSearch to find the state agency's own downloadable list of licensed
   assisted living homes with bed counts (and, ideally, the administrator, phone, website or email). Only a state
   agency site counts. Never a directory, a data seller or a GitHub copy (one tested on 11/2 was made up).
   Copy `tools/lead_list/sources/nc_dhsr.py` to `<st>_<agency>.py`, set the page, `how_to`, aliases, the
   assisted living type filter and `care`, and register it in `sources/__init__.py`. Add a test with 3 synthetic
   rows to `tools/lead_list/tests/` and run the tests
   (`python -m unittest discover -s tools/lead_list/tests -t .`). At the end, tell Joey the new module exists and
   ask before committing it (synthetic test data only: the repo is public).
2. **Runway.** `python -m tools.lead_list.runway --data <DATA>` (add `--pace 140` for the after-11/08 pace).
   It prints sendable homes left, the pace, and days left. Read only.
3. **Get the file.** Download it from the link step 1 printed (`curl -L -o <OUT>\<st>-files\<st>.xlsx "<link>"`)
   or, when the site needs a form (Florida: search Provider Type "Assisted Living Facility" statewide, then "Export
   to Excel"), use the browser or ask Joey to click it once. If the site says the result is too large, export one
   county or area at a time into the same empty folder `<OUT>\<st>-files\` and use that folder as `<FILE>`
   (overlaps are fine). HTML-table and Excel 2003 XML exports are read as they are; an old binary `.xls` must be
   saved as `.xlsx` or `.csv` first (the tool says so).
4. **Inspect.** `python -m tools.lead_list.run inspect --state <st> --file <FILE>`
   - Every required field (`name`, `beds`) must map. Check that `administrator`, `phone`, `license`, `city`,
     `county` and `type` map too. If a column is missing, add its header to the module's `aliases` and re-run.
   - Read "license types seen". If an assisted living type is filtered out, or a non-assisted-living type kept,
     fix `include_type` and re-run.
   - Read the "greetings" lines. If the first names shown are really last names (the list prints `EXAMPLE PAT`
     with no comma), set `admin_order = "last_first"` in the state's module and re-run. A company in the
     administrator cell gives no name ("Hi,"), which is correct.
5. **Build.** `python -m tools.lead_list.run build --state <st> --file <FILE> --data <DATA> --out <OUT>`
   - Up to 50 minutes (`--minutes`). If it stops on time, run the same command again: it continues from
     `web_cache.json`.
   - Exit 2: a column did not map (back to step 4). Exit 3: the network refused the download (step 1).
   - A `web step: BLOCKED` line means no websites or emails were looked up. Stop, same final message as step 1.
6. **Extra sites** (judgment, optional, at most 30 homes). List the biggest homes with no website and no email:
   `python -m tools.lead_list.run review --state <st> --out <OUT> --show no-email --limit 30`.
   For each, use WebSearch to find the
   home's own official website (never a directory such as A Place for Mom, Caring.com or Yelp). Write
   `<OUT>\<st>\extra_sites.csv` with columns `id,website`, then re-run step 5 with `--sites <that file>`.
   Python keeps a site only if the page shows the home's phone or street address.
7. **Names** (judgment). Print the names email 1 will use:
   `python -m tools.lead_list.run review --state <st> --out <OUT> --show names --limit 2000`
   (`id | home | official name`). Email 1 says "how many rooms are open at
   <home> right now?". If a name reads like a license record, not like what the staff call the home, write
   `<OUT>\<st>\names.csv` (`id,home`) with a clean short name or `your home`, then re-run step 5 with
   `--names <that file>` (and `--sites` if you used it). Never invent a name; shorten or use `your home`.
8. **Report to Joey** from `<OUT>\<st>\summary.json`: homes on the list, assisted living 40+ beds, new to the
   campaign, with website, with email, ready to load, named greetings, expected to pass the mailbox check, and days
   of runway added. Show 10 random `include` rows:
   `python -m tools.lead_list.run review --state <st> --out <OUT> --show sample --limit 10`
   (`first name | home | city | beds | email source`). Never read the whole `review.csv` into the chat.
   Ask: "Load these <n> homes?" In a dry run, stop here.
9. **Load** (only after Joey says yes). Follow `<OUT>\<st>\HOW-TO-LOAD.md` exactly:
   `python tools/cloud_state.py pull` (engine repo), then
   `python -m tools.lead_list.merge --batch <OUT>\<st> --data <DATA>` (dry run, read the skips), then the same
   with `--write`, then in the engine repo
   `python tools/cloud_state.py push-local queue.json lead_facts.json build/prospects.json`.

## What lands where
- `<OUT>\<st>\`: `review.csv`, `queue_additions.json`, `lead_facts_additions.json`, `prospects_additions.json`,
  `summary.json`, `HOW-TO-LOAD.md`, `web_cache.json`, and after a load a `backup-<time>\` folder.
- On load only: three PC-owned engine files get new entries appended (`queue.json`, `lead_facts.json`,
  `build/prospects.json`), then push-local publishes them. Nothing else changes.
- Never in this repo: no state data, names, emails or phone numbers are ever committed here (it is public).

## Hard rules
- Never send an email. The engine sends, after its own nightly mailbox check.
- Never load without Joey's yes. Never edit `carehome.db` or any cloud-owned state file. Never push anything but
  the three files above, and only with `cloud_state.py push-local`.
- 40+ licensed beds, assisted living licenses, active licenses. Do not lower `--min-beds` unless Joey says so.
- Emails come only from the home's own site or the state list. Never guess an address, never use one from a
  directory or a data seller.
- The copy is Joey's locked v3. Do not edit any email text. Only the `home` name may change (step 7).
- Never print, echo or look for an API key. No GoHighLevel, Notion or Gmail writes.

## Final message format
One line:
`Lead List <ST>: <ready> homes ready (<with email> with email of <new> new, <40+> at 40+ beds, <on list> on the list), about <days> days of runway. <Loaded and pushed | Waiting for your OK | Dry run>.`
