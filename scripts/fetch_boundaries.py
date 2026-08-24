#!/usr/bin/env python3
"""Documented, NOT yet runnable in this sandbox: real admin boundary ingestion.

This sandbox's network egress is limited to package registries (pypi/npm/etc)
and github -- it cannot reach GADM, HDX, or Natural Earth. This script
documents exactly what a real ingestion pass needs to do; run it from an
environment with open network access.

Steps this script performs once network access is available:
  1. Download GADM level 0-3 GeoPackages for IND, KEN, UGA, TZA, ZAF
     (https://gadm.org/download_country.html)
  2. Download Ethiopia admin boundaries from OCHA HDX COD-AB instead of GADM
     (GADM is stale post-2020/2021 splits -- see geography_crosswalk.json)
  3. Simplify geometries with mapshaper/topojson at zoom-appropriate tolerances
     for vector-tile serving (do NOT simplify past the point where adjacent
     units still share exact boundary vertices -- required for clean 3D
     extrusion and click-precision, see docs/ARCHITECTURE.md §3D map notes)
  4. Assign each feature a stable admin_id matching this repo's `geography.json`
     scheme, and populate `geometry_version`
  5. Emit PMTiles (or MVT) per level for MapLibre/deck.gl consumption
"""
import sys

REQUIRED_BUT_UNAVAILABLE_DOMAINS = ["gadm.org", "data.humdata.org", "naturalearthdata.com"]


def main() -> int:
    print("This script is a documented placeholder -- see module docstring.")
    print(f"Requires network access to: {', '.join(REQUIRED_BUT_UNAVAILABLE_DOMAINS)}")
    print("Not runnable in the build sandbox that produced this repo.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
