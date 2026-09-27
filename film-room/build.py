#!/usr/bin/env python3
"""Build the Film Room page from a data folder.

    python3 build.py DATA_DIR OUT.html

DATA_DIR holds any of these JSON files (all optional):
    calls*.json          arrays of call breakdowns (merged in file-name order)
    playbook.json        house playbook + coach rubric
    evidence.json        {"items": [...], "gaps": [...]}
    proof.json           proof cards, one per objection category
    personas_extra.json  composite sparring opponents
    patterns.json        cross-call patterns (strings or {title, detail})
    model.json           deal-math scenarios, offers and presets
    meta.json            page copy overrides

Real call data is private. Keep it outside this repo; data/example/ holds
made-up sample data so the page can be built and tried without it.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def gather(data_dir):
    d = pathlib.Path(data_dir)
    out = {"calls": []}
    for p in sorted(d.glob("calls*.json")):
        chunk = load(p)
        out["calls"].extend(chunk if isinstance(chunk, list) else [chunk])
    for name in ("playbook", "evidence", "proof", "personas_extra", "patterns", "model", "meta"):
        p = d / f"{name}.json"
        if p.exists():
            out[name] = load(p)
    # drop duplicate calls (same id), keeping the first
    seen, calls = set(), []
    for c in out["calls"]:
        cid = c.get("call_id")
        if cid in seen:
            continue
        seen.add(cid)
        calls.append(c)
    out["calls"] = calls
    return out


def build(data_dir, out_path):
    data = gather(data_dir)
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # "<" only occurs inside JSON strings, so escaping it keeps the data
    # from closing its <script> element early (</script>, <!--)
    blob = blob.replace("<", "\\u003c")
    html = (HERE / "template.html").read_text(encoding="utf-8")
    if "/*__DATA__*/" not in html:
        raise SystemExit("template is missing the /*__DATA__*/ placeholder")
    html = html.replace("/*__DATA__*/", blob)
    pathlib.Path(out_path).write_text(html, encoding="utf-8")
    print(f"wrote {out_path}: {len(html):,} bytes, {len(data['calls'])} calls, "
          f"{len(data.get('evidence', {}).get('items', []))} evidence items, "
          f"{len(data.get('proof', []))} proof cards")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2])
