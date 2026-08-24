#!/usr/bin/env python3
"""Checks the geography seed's admin1 counts against the counts your original
dump specified per country, and flags any drift. Run this after any geography
edit -- it's the guardrail against silently losing/duplicating a state."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# NOTE on TZA=31: the original project dump's header said "30 regions" but its
# own enumerated list actually contained 31 names (it includes Songwe, the
# 2016 split from Mbeya). The enumerated list is the ground truth here, not
# the header count -- geography.json correctly has 31, so this expects 31.
EXPECTED = {"IND": 36, "KEN": 47, "UGA": 58, "TZA": 31, "ETH": 11, "ZAF": 9}


def main() -> int:
    geo = json.loads((ROOT / "data" / "seed" / "geography.json").read_text())
    ok = True
    for country_id, expected in EXPECTED.items():
        actual = len([u for u in geo["admin1"] if u["country_id"] == country_id])
        status = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            ok = False
        print(f"{country_id}: expected={expected} actual={actual} [{status}]")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
