"""Which homes may join the campaign: assisted living, an active license, and 40+ licensed beds (Joey, 10/23)."""
from . import common


def check(source, rec, min_beds=common.MIN_BEDS):
    """-> (True, '') or (False, the reason in plain words)."""
    if not rec.get("facility"):
        return False, "no facility name"
    ok, why = source.include_type(rec.get("type", ""))
    if not ok:
        return False, why
    ok, why = source.active(rec.get("status", ""))
    if not ok:
        return False, why
    beds = rec.get("beds")
    if beds is None:
        return False, "no bed count on the state list"
    if beds < min_beds:
        return False, f"under {min_beds} beds ({beds})"
    return True, ""


def apply(source, recs, min_beds=common.MIN_BEDS):
    """Sets rec['decision'] ('keep' or 'exclude') and rec['reason']. Returns the kept records."""
    kept = []
    for r in recs:
        ok, why = check(source, r, min_beds)
        r["decision"], r["reason"] = ("keep", "") if ok else ("exclude", why)
        if ok:
            kept.append(r)
    return kept
