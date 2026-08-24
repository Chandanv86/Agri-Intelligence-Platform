# Architecture

This implements the design from `Card_Architecture_Final_Review_and_Gaps.md`
(included in this repo's project history / provided separately). Summary:

## §3 — Click → snapshot pipeline

```
CLICK GEOMETRY (any level, incl. country/Level 0)
  -> resolve admin_id via geography_crosswalk (GeographyService.resolve)
  -> resolve max supported depth (village-coverage / MMU rules)
  -> resolve crop_id + season_id (season list can be >1 concurrent per country-region)
  -> pull evidence: Sentinel-2, Sentinel-1, Dynamic World, (AMED if India), weather
  -> compute sowing/establishment state (analytics/sowing.py)
  -> compute yield state + gap + production + economic exposure (analytics/yield_gap.py)
  -> compute confidence (analytics/confidence.py, AMED-aware for India)
  -> publish ONE AgriSnapshot with computation_trace_id (services/snapshot.py)
  -> render cards (services/card_manifest.py filters the 32-card manifest by
     what fields are actually present) + map
```

No card independently calls a second endpoint. `/api/v1/agri/areas/{admin_id}/snapshot`
is the only endpoint the frontend calls to render a full card panel.

## §4 — Card stack (32 cards, 3 tiers)

Machine-readable in `data/seed/card_manifest.json`. Tier 1 = always visible,
Tier 2 = expandable, Tier 3 = advanced/analyst mode. The frontend
(`app/static/app.js`) renders purely from this manifest plus the snapshot
payload — no card list is hardcoded in a component.

## Country adapters (§2.8, §122)

`app/services/country_adapters/` — one class per country, implementing
hierarchy level names, crop-mask primary/fallback source, price currency,
price-granularity confidence note, and rainfall source. This is the seam
that keeps six countries' worth of agronomic and institutional differences
out of scattered `if country == "KEN"` conditionals.

## Geography crosswalk (§2.1 — the biggest fix in this pass)

`data/seed/geography_crosswalk.json` resolves legacy province/region names
(Kenya's 8 provinces, Uganda's 4 regions, Tanzania's Zanzibar naming) to the
real clickable admin_ids. It also carries an explicit, unresolved flag for
Ethiopia, whose GADM boundary data predates the 2020/2021 Sidama and South
West Ethiopia Peoples' Region splits — this is a real blocker, not a
crosswalk problem, and the code says so rather than pretending it's fixed.

Run `python scripts/validate_crosswalk.py` to see current resolution status.
Run `python scripts/validate_geography_counts.py` to check admin1 counts
against the source-of-truth enumeration.

## Data-status discipline

Every metric-bearing schema carries a `DataStatus` (`app/schemas/common.py`):
OBSERVED / MODELLED / ESTIMATED / DERIVED / FORECAST / HISTORICAL / PROXY /
SCENARIO / DEMO / UNAVAILABLE. This build runs entirely in DEMO mode (see
`docs/KNOWN_LIMITATIONS.md`) — every snapshot is honestly labeled
`data_status: DEMO`, and connector `SourceRef.fired` is `False` for every
external source unless live credentials are actually configured
(`Settings.is_live_capable()`). Confusing DEMO output for LIVE output is the
one failure mode this architecture is built to make structurally hard.

## Multi-season calendars (§2.9)

`data/seed/seasons.json` allows more than one concurrent season per
country/crop (Ethiopia Belg + Meher, Kenya/Tanzania long + short rains,
Uganda's two maize seasons) instead of assuming one annual block.

## Frontend / map architecture

`app/static/app.js` implements the click-to-drill state machine directly
against MapLibre GL JS (globe projection), with exactly one active layer
click handler at a time (`setActiveHandler`) — this specifically fixes a bug
where a deeper layer (e.g. districts) and its parent layer (state) would
both fire on the same click once districts were loaded on top of a state
polygon. Real boundary polygons are static files under
`app/static/boundaries/` (see `docs/BOUNDARY_DATA_SOURCES.md`); the only
backend involvement in the map itself is `/api/v1/geography/match`, which
batch-resolves a boundary polygon's on-the-ground name to this project's
`admin_id` registry so a click can be turned into a snapshot request.

## MVP scope actually implemented here (§7)

Two states only: Punjab (Ludhiana + 9 other districts) and Bihar (Patna + 9
other districts) have registry `admin_id`s wired to the MVP pilot. Real
boundary geometry is far broader than that — all 35 India states/UTs have
real district polygons, and all 6 countries have real admin-1 polygons — but
clicking anywhere outside Ludhiana/Patna correctly returns `501` (no fixture)
or shows "not yet in registry" (no `admin_id` match at all) instead of a
fabricated snapshot. See `app/services/snapshot.py::_FIXTURE_FILES`.
