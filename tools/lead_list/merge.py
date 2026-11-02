"""Load a lead_list batch into the engine's PC-owned files. Run on Joey's PC (or any checkout of the engine's
state), AFTER `python tools/cloud_state.py pull` and BEFORE `python tools/cloud_state.py push-local ...`.

  python -m tools.lead_list.merge --batch <batch folder> --data <engine>/data/carehome          (dry run)
  python -m tools.lead_list.merge --batch <batch folder> --data <engine>/data/carehome --write  (writes)

What it does, in order:
  1. Reads queue.json, lead_facts.json and build/prospects.json from --data, and carehome.db read-only.
  2. Checks every batch home again against them (the queue may have changed since the batch was built): same id,
     license number, name and city, phone or email. Duplicates are skipped and listed.
  3. Re-numbers the batch's ranks to sit just below the lowest rank now in queue.json, keeping the batch order.
  4. With --write: copies the three files into <batch>/backup-<time>/, appends the new entries, writes each file
     back in its own JSON layout, and reads them back to prove they parse.
It never touches carehome.db (cloud-owned) or any other state file, and never pushes anything.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys

from . import common
from .dedupe import Index

FILES = {"queue": "queue.json", "facts": "lead_facts.json", "people": os.path.join("build", "prospects.json")}


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _layout(path, default_indent):
    """(indent, ensure_ascii, newline) the file already uses, so a merge only adds lines. The engine files are
    written on Windows: CRLF, no newline at the end, queue.json with raw accents, the others with \\u escapes."""
    if not os.path.exists(path):
        return default_indent, False, "\n"
    with open(path, "rb") as f:
        raw = f.read()
    lines = raw[:4096].split(b"\n")
    indent = default_indent
    if len(lines) > 1:
        indent = len(lines[1]) - len(lines[1].lstrip(b" "))
    has_raw = any(b > 127 for b in raw)
    has_esc = b"\\u" in raw
    newline = "\r\n" if b"\r\n" in raw[:4096] else "\n"
    return indent, (has_esc and not has_raw), newline


def _write(path, obj, layout):
    indent, ascii_, newline = layout
    tmp = path + ".lead_list.tmp"
    with open(tmp, "w", encoding="utf-8", newline=newline) as f:
        json.dump(obj, f, indent=indent, ensure_ascii=ascii_)
    os.replace(tmp, path)


def plan(batch, data):
    q_add = _read(os.path.join(batch, "queue_additions.json"), [])
    f_add = _read(os.path.join(batch, "lead_facts_additions.json"), {})
    p_add = {p["id"]: p for p in _read(os.path.join(batch, "prospects_additions.json"), [])}
    ix = Index.load(data)
    keep, skipped, batch_ix = [], [], Index()
    for q in sorted(q_add, key=lambda x: -x["rank"]):
        f = f_add.get(q["id"], {})
        rec = {"id": q["id"], "state": f.get("state") or q["id"].split("-")[0].upper(),
               "license": common.id_license_token(q["id"]), "official_name": q["facility"],
               "facility": q["facility"], "city": f.get("city", ""), "phone": f.get("phone", "")}
        why = ix.match(rec, q["email"]) or batch_ix.match(rec, q["email"])
        if why:
            skipped.append((q["id"], why))
            continue
        batch_ix.remember(rec, q["email"])
        keep.append(q)
    start = (ix.min_rank if ix.min_rank is not None else 0) - 1
    for n, q in enumerate(keep):
        q["rank"] = start - n
    return {"queue": keep, "facts": {q["id"]: f_add[q["id"]] for q in keep if q["id"] in f_add},
            "people": [p_add[q["id"]] for q in keep if q["id"] in p_add], "skipped": skipped,
            "index_counts": ix.counts, "rank_start": start}


def apply(batch, data, p):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(batch, f"backup-{stamp}")
    os.makedirs(bdir, exist_ok=True)
    paths = {k: os.path.join(data, v) for k, v in FILES.items()}
    for k, path in paths.items():
        if os.path.exists(path):
            shutil.copy2(path, os.path.join(bdir, os.path.basename(path)))
    layouts = {"queue": _layout(paths["queue"], 1), "facts": _layout(paths["facts"], 0),
               "people": _layout(paths["people"], 1)}
    queue = _read(paths["queue"], [])
    facts = _read(paths["facts"], {})
    people = _read(paths["people"], [])
    n0 = (len(queue), len(facts), len(people))
    queue += p["queue"]
    for k, v in p["facts"].items():
        facts.setdefault(k, v)
    have = {x.get("id") for x in people}
    people += [x for x in p["people"] if x["id"] not in have]
    os.makedirs(os.path.dirname(paths["people"]), exist_ok=True)
    _write(paths["queue"], queue, layouts["queue"])
    _write(paths["facts"], facts, layouts["facts"])
    _write(paths["people"], people, layouts["people"])
    back = (len(_read(paths["queue"], [])), len(_read(paths["facts"], {})), len(_read(paths["people"], [])))
    return {"before": n0, "after": back, "backup": bdir}


def main(argv=None):
    common.safe_stdout()
    ap = argparse.ArgumentParser(prog="lead_list.merge")
    ap.add_argument("--batch", required=True, help="the batch folder (holds queue_additions.json)")
    ap.add_argument("--data", required=True, help="the engine's data/carehome folder, freshly pulled")
    ap.add_argument("--write", action="store_true", help="write the files (default: dry run)")
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.data, "queue.json")):
        print(f"no queue.json in {a.data}: run `python tools/cloud_state.py pull` in the engine repo first")
        return 2
    p = plan(a.batch, a.data)
    print(f"batch homes to add: {len(p['queue'])} (ranks {p['rank_start']} down), skipped as duplicates: "
          f"{len(p['skipped'])}")
    for pid, why in p["skipped"][:50]:
        print(f"  skip {pid}: {why}")
    if not a.write:
        print("dry run: nothing written. Add --write to append them.")
        return 0
    if not p["queue"]:
        print("nothing new to add; files unchanged")
        return 0
    r = apply(a.batch, a.data, p)
    print(f"written. queue.json {r['before'][0]} -> {r['after'][0]}, lead_facts.json {r['before'][1]} -> "
          f"{r['after'][1]}, build/prospects.json {r['before'][2]} -> {r['after'][2]}. Backup: {r['backup']}")
    print("next: python tools/cloud_state.py push-local queue.json lead_facts.json build/prospects.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
