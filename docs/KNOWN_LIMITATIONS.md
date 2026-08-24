# Known Limitations — read this before treating anything here as "live"

Honesty about what's real vs. scaffolded is the actual design philosophy of
this project (carried over from the demo-fixture-audit rule in the original
repo). This file is the single place that states it plainly.

## 1. This build ships in DEMO mode only

No Sentinel Hub, GEE, AMED, or weather credentials are embedded anywhere in
this repo (see `.env.example`). Every snapshot returned by the API is built
from a deterministic JSON fixture (`data/examples/demo_fixture_*.json`), not
a live satellite/model computation. `data_status: "DEMO"` is stamped on every
response, and every `SourceRef.fired` for external connectors is `False`
unless real credentials are supplied and `Settings.is_live_capable()` returns
`True`.

**Going LIVE for real** requires: Sentinel Hub / CDSE OAuth client
credentials, a GEE service account + registered Cloud project, and — for
India specifically — a Google-allowlisted AMED API key (see §6 below). None
of these can be provisioned inside this build sandbox.

## 2. Only 2 of ~700+ Indian districts have real analytical data wired

The MVP pilot scope (per the review doc §7) is Ludhiana (Punjab) and Patna
(Bihar), Rice / Kharif 2026 only. The other 18 districts seeded in
`geography.json` (`admin2_mvp_pilot`) exist for hierarchy/UI testing but
return `501` from `/snapshot` — there is no fixture backing them and there
must not be a silent fallback that invents one.

## 3. Real boundary geometry now ships, but only goes as deep as real free data allows

`app/static/boundaries/` (~2.1 MB) has real WGS84 boundaries: all 6
countries' admin-1 layer, and India's full admin-2 (district) layer for all
35 states/UTs. See `docs/BOUNDARY_DATA_SOURCES.md` for exact sources and a
real projection bug that was caught and fixed while sourcing this data.

What this does NOT include:
- Sub-district/village-level geometry anywhere (India villages, Uganda
  sub-counties, Kenya wards, etc.) — the click-to-drill map stops at
  district level for India and at admin-1 for the other 5 countries.
- Real county-level geometry for Kenya (only the 8 legacy provinces are
  freely available at this resolution; counties are offered as a list, not
  map polygons, after clicking a province).
- Any geometry beyond what `scripts/fetch_boundaries.py` documents as still
  needing a GADM/HDX pull from an environment with open network access
  (this sandbox could not reach `gadm.org` or `data.humdata.org`).

## 4. Uganda's region→district crosswalk is an explicit placeholder

`geography_crosswalk.json`'s four Uganda groups intentionally contain
`"placeholder -- requires authoritative region-to-district crosswalk..."`
rather than a fabricated mapping. `scripts/validate_crosswalk.py` fails CI
(non-zero exit) until this is replaced with a real UBOS-sourced table.

## 5. Ethiopia's admin-1 boundaries are known-stale and unresolved

GADM's 11-region Ethiopia dataset predates the 2020 Sidama split and the 2021
South West Ethiopia Peoples' Region split. This is not fixable by a
crosswalk table — it needs a new boundary source (OCHA/HDX or Ethiopia's
statistics agency). `geography_crosswalk.json.ethiopia_boundary_staleness_flag.status`
is `"unresolved_blocker_for_ethiopia_v1"`. Do not enable Ethiopia in
production until this is replaced.

## 6. AMED (Google DeepMind) is India-only and requires allowlisting

Per Google's own FAQ, AMED currently covers India only, and API access
requires Google to allowlist your GWCID — there is no self-service key.
`app/services/connectors/amed.py` enforces this: it raises
`AmedNotAvailableForCountry` immediately for any non-India call rather than
making a doomed HTTP request.

## 7. Kenya/Uganda/Tanzania/Ethiopia price and statistics granularity is weaker than India's

This is reflected honestly in each `CountryAdapter.price_granularity_note()`
and should continue to inform the confidence model rather than being
smoothed over — see review doc §2.5.

## 8. What IS real in this build

- The full analytics math (sowing progress, yield gap, aggregation,
  confidence, Moran's I, staleness penalties) — genuinely implemented,
  unit-tested, no shortcuts.
- The FastAPI service layer, snapshot orchestration, and 32-card manifest
  filtering — genuinely wired end-to-end (`pytest` passes, 78/78).
- **A real clickable globe** (MapLibre GL JS, vendored locally, no CDN
  dependency) with real WGS84 boundary polygons: world → country → state
  /province/region/county → (India only) district, verified with headless
  browser tests that actually click through the whole drill-down and confirm
  cards render — not just a static screenshot check. See
  `docs/BOUNDARY_DATA_SOURCES.md`.
- The connector *code* for Sentinel Hub Statistics API, CDSE STAC, GEE
  (Sentinel-2/-1, Dynamic World, ERA5-Land, CHIRPS, WorldCereal), and AMED —
  real API contracts, ready to run the moment credentials exist.
- The geography crosswalk fixes for Kenya/Tanzania and the Daman-and-Diu
  merge/village-depth rules for India — real, tested, correct.

## 9. The globe is MapLibre's "globe" projection, not a Cesium-style 3D terrain globe

`app/static/vendor/maplibre-gl/` is vendored MapLibre GL JS with
`projection: "globe"` — this renders a genuine rotating 3D sphere with real
click-to-drill boundary interaction, and was chosen over CesiumJS
specifically because it ships a working, testable result without an Ion
access token or a build step. It does not have Cesium's terrain elevation
or photorealistic imagery. If true 3D terrain draping is a hard requirement
later, swapping the map library is a frontend-only change — the
`admin_id`-in / snapshot-JSON-out contract with the backend doesn't change.
