#!/usr/bin/env python3
"""Flags crosswalk groups that still contain a 'placeholder' entry -- i.e.
groups that are NOT yet safe to treat as authoritative. This is meant to run
in CI so a real crosswalk table never gets silently treated as finished."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    data = json.loads((ROOT / "data" / "seed" / "geography_crosswalk.json").read_text())
    unresolved = [
        g for g in data["groups"]
        if any(str(a).startswith("placeholder") for a in g["maps_to_admin_ids"])
    ]
    for g in unresolved:
        print(f"UNRESOLVED: {g['country_id']} / {g['legacy_name']} -- {g['note']}")
    eth = data["ethiopia_boundary_staleness_flag"]
    print(f"\nEthiopia boundary flag: {eth['status']}")
    if unresolved or eth["status"] != "resolved":
        print(f"\n{len(unresolved)} crosswalk group(s) unresolved. This is expected pre-production "
              f"(see docs/KNOWN_LIMITATIONS.md) but must be closed before enabling Uganda/Ethiopia in prod.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
