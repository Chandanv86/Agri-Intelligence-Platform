# Boundary Data Sources

Real, freely-licensed boundary geometry now ships with this repo under
`app/static/boundaries/` (~2.1 MB total). This documents exactly where it
came from, and a real bug that was caught and fixed while sourcing it.

## Sources used

| Layer | Source | License | Notes |
|---|---|---|---|
| World (all countries, context layer) | Natural Earth `ne_110m_admin_0_countries` | Public domain | Filtered to properties `{iso-a3, name}` |
| World (6 supported countries, highlighted) | Natural Earth `ne_110m_admin_0_countries` | Public domain | Same source, filtered by ISO A3 |
| Admin-1 (state/province/region/county) — all 6 countries | Natural Earth `ne_10m_admin_1_states_provinces` | Public domain | Filtered per country by `adm0_a3` |
| Admin-2 (district) — India, all 35 states/UTs | geohacker/india (GADM-derived, community-maintained) | Same terms as GADM (free for non-commercial/academic use; check GADM's terms before commercial redistribution) | Older vintage (~pre-2014) — see "Known divergences" below |

All files were simplified with `mapshaper` (`-simplify weighted N% keep-shapes`,
`keep-shapes` specifically to prevent small features like Lakshadweep from
being simplified into null geometry — see the regression test at
`tests/unit/test_boundary_data_integrity.py`).

## A real bug this surfaced: EPSG:54003, not WGS84

The first source tried for admin-1 boundaries was
`highcharts/map-collection-dist` on GitHub. Its `.geo.json` files use a
**Miller cylindrical projection (EPSG:54003)**, not WGS84 lng/lat, despite
the `.geo.json` name and despite looking like normal GeoJSON. Coordinates
looked like `[6818, 7133]` — clearly not degrees, but structurally valid
enough that nothing crashed. The practical effect: every map click missed
every feature, silently, because `map.project(lng, lat)` was computing
screen positions for a coordinate system the polygons weren't actually in.

This was only caught by browser-level testing (`queryRenderedFeatures` at
the click point returning nothing) — a manual "does it look right" check on
a screenshot would not have caught it, since the base map and world-context
layer rendered fine regardless. **Lesson encoded as a permanent test:**
`test_every_boundary_file_has_valid_wgs84_coordinates` in
`tests/unit/test_boundary_data_integrity.py` checks every coordinate in
every shipped boundary file is within `[-180,180] x [-90,90]` — this would
have caught the bug in CI before it ever reached a browser.

The fix was switching to Natural Earth, which correctly declares
`"crs": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}` and actually uses it.

## Known divergences between geometry and this project's admin registry

See `docs/KNOWN_LIMITATIONS.md` for the full list; summarized here because
it's geometry-specific:

- **Kenya**: Natural Earth's admin-1 geometry for Kenya is the 8 legacy
  provinces (Coast, Nyanza, Central, ...), not the 47 real counties — this
  is simply the finest free geometry available for Kenya at this scale.
  The map shows provinces; the county-level `geography_crosswalk.json`
  grouping is used to offer real counties as a list once a province is
  clicked, per `app/services/geography_match.py`.
- **Uganda**: Natural Earth's 112 districts are a more current district
  count than the 58-district figure in this project's original geography
  seed (Uganda splits districts frequently). Most of the 112 map polygons
  will not match an `admin_id` in the registry yet and will show as "not
  yet linked" when clicked — this is expected, not a bug.
- **Tanzania**: Natural Earth spells some regions differently (`Dar-Es-Salaam`
  vs. the registry's `Dar es Salaam`) and groups Zanzibar's sub-regions
  differently than the registry does. A handful of confident 1:1 aliases are
  handled in `app/services/geography_match.py`; ambiguous groupings (e.g.
  `Zanzibar South and Central`) are deliberately left unmapped rather than
  guessed. `Songwe` (a 2016 split from Mbeya) doesn't exist in this vintage
  of Natural Earth data at all.
- **India**: the district-level (admin-2) source is an older vintage GADM
  derivative — it predates Telangana (2014) and still shows undivided
  Andhra Pradesh at the district level, and uses "Orissa"/"Uttaranchal"
  (renamed to Odisha/Uttarakhand in the shipped files, but the underlying
  district split itself is not updated). Telangana therefore has no
  district-level boundary file; clicking it falls through to a direct
  snapshot attempt at the state level instead.

## Regenerating this data

See `scripts/fetch_boundaries.py` for the (currently sandbox-blocked, but
documented) path to pulling fresher/authoritative sources — GADM current
release, OCHA HDX for Ethiopia specifically, and UBOS for an authoritative
Uganda region→district crosswalk.
