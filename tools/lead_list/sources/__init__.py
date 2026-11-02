"""State source modules. Add a state: copy nc_dhsr.py, change the page, aliases and type filter, register it here."""
from . import fl_ahca, nc_dhsr

REGISTRY = {s.code: s for s in (fl_ahca.SOURCE, nc_dhsr.SOURCE)}


def get(code):
    code = (code or "").strip().lower()
    if code not in REGISTRY:
        raise SystemExit(f"no source module for state '{code}'. Known: {', '.join(sorted(REGISTRY))}. "
                         "Add one in tools/lead_list/sources/ (copy nc_dhsr.py).")
    return REGISTRY[code]
