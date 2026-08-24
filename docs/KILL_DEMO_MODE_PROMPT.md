# Prompt — Kill DEMO Mode, Rebuild the Card Stack Around What Is Actually Live-Feasible

Corrected against the real repo on 2026-08-23. Every path and seam below was
verified to exist. Execute in three commits, in order; do not start commit N+1
until commit N boots and `pytest` passes.

## Ground truth about this codebase (do not assume otherwise)

There is no `app/services/live_snapshot.py` and no `app/services/boundary_geometry.py`,
and there is no `LiveIndicators` type anywhere. Everything live lives in one
file, `app/services/snapshot.py`:

- `SnapshotService` — the DEMO fixture service. `_FIXTURE_FILES` (line 33),
  `_load_fixture`, `build_sowing`, `build_yield`, `build_situation`. This is the
  thing being deleted. It is the only producer of `DataStatus.DEMO`
  (lines 110, 135, 153, 181).
- `LiveSnapshotBuilder` — the real connector fan-out, with an internal `probe()`
  helper that isolates each connector failure into `fired=False`.
- `SnapshotOrchestrator` — the router (`resolve_source()`, `get_snapshot()`).
  **This is the seam to change**, and it has two callers:
  `app/api/routes.py` (line 19, `_orchestrator`) and `app/workers/tasks.py`.
  Change both or they drift.
- Geometry helpers, also in this file: `geometry_for()`, `_geometry_to_bbox()`,
  `_geometry_centroid()`, `_ring_area_ha()`, `_estimate_admin_area_ha()`
  (shoelace + cos-latitude, no geo dependency).

Fixture JSON lives in `data/examples/`, not `data/fixtures/`:
`demo_fixture_punjab_rice_kharif.json`, `demo_fixture_bihar_rice_kharif.json`.

`CardManifestService.renderable_cards()` is a **method**, not a manifest field.
It drops a card when any dotted path in that card's `requires` array resolves to
`null`, `[]` or `{}`. Twelve of the 32 cards currently declare `requires: []`,
which is not a gate — it is an unconditional pass, and it is why dead cards
render the literal string `null`. To hide a card, give it real `requires` paths.

`app/static/` has **no charting library** — only vendored maplibre-gl, which is
a map renderer. See commit 3 for the decision.

`DEFAULT_DATA_STATUS` is declared at `app/core/config.py:25` and read by nothing.
Dead setting; deleting it cannot break anything.

## Commit 1 — Eradicate DEMO mode

Write the replacement tests **first**, before deleting anything, so there is
never a window with no coverage. `tests/integration/test_api.py` currently has
`test_snapshot_happy_path_ludhiana` (line 43) and `test_snapshot_happy_path_patna`
(line 59); those two fixtures are the only thing exercising the full snapshot
response shape without network access. Replace them with tests that monkeypatch
the connector layer (`SentinelHubStatisticsClient.statistics`,
`EarthEngineConnector`, `WeatherContextClient`, `WorldCerealClient`) and assert
on the live shape. Never let a test reach real Sentinel Hub or GEE.

Then:

1. Delete `_FIXTURE_FILES`, `_load_fixture`, `_EXAMPLES_DIR`, and the whole
   `SnapshotService` class from `app/services/snapshot.py`.
2. Simplify `SnapshotOrchestrator.resolve_source()` to two outcomes: registered
   → LIVE, unknown → `UnknownAdminUnit` (404). Delete `SnapshotSource.FIXTURE`
   and the `NoFixtureAvailable` 501 branch. Mirror the change in
   `app/workers/tasks.py`.
3. When `settings.is_live_capable()` is `False`, return an explicit
   **503** with the message "no live evidence connector configured — see
   .env.example". Never a fixture fallback, never a plausible-looking number.
4. Delete the two files in `data/examples/`.
5. Delete `default_data_status` from `config.py` and `DEFAULT_DATA_STATUS` from
   `.env` and `.env.example`.
6. Leave `DataStatus.DEMO` defined in the enum (removing an enum value that old
   stored payloads may reference is riskier than simply never emitting it) but
   assert in a test that no request path can produce it.
7. Rewrite `showNotLiveMessage` in `app/static/app.js` (line 306) and the catch
   block at line 319 — both currently name-drop "Ludhiana (Punjab) and Patna
   (Bihar)" as the only real data. Replace with the actual condition:
   credentials configured or not, connector reached or not.
8. **Decide explicitly** what happens to `build_yield` and the
   `yield_performance` schemas. Once the fixtures are gone nothing produces them,
   so they become unreachable code. Recommendation: keep the schema definitions
   dormant for when the baseline table lands, delete the fixture-only builder.
   State which you chose in the commit message.
9. Update `docs/KNOWN_LIMITATIONS.md` and `docs/ARCHITECTURE.md`: the real
   limitation is now "no historical baseline, no price data, no pixel-level
   exports", not "only 2 districts have fixtures".

"Eradicate demo mode" does **not** mean "make every card work anyway". Commit 2
removes cards. The honesty invariant — `SourceRef.fired`, never substituting a
plausible number for a missing one — binds harder now that the fixture safety
net is gone, not softer.

## Commit 2 — Retier the card stack

### Kill these first: demo-grade numbers already leaking into LIVE

These are more urgent than any card removal, because they are fabrications
already on screen in live mode:

- `weekly_rate_pp` is hardcoded `0.0` at `snapshot.py:738` with the comment
  "no live weekly history series yet". Tier-1 Sowing Trend renders that fake
  zero as if it were measured. Either compute it (see the NDVI series below) or
  set it to `None` and let `requires` hide the card.
- `historical_consistency` is pinned to `0.5` in the live confidence components
  (`snapshot.py:719`) and feeds the headline confidence score.
- `stage_distribution`'s `emerging` is hardcoded `0.0` (`snapshot.py:669`).
- **The big one**: `target_area_ha` derives from a *generic* cropland fraction
  (Dynamic World crop probability, or WorldCereal `temporarycrops`), not a
  rice-specific mask. `sowing_progress`'s `deviation`, `status` and `risk_label`
  compare that generic number against the *rice* calendar. That is a larger
  fabrication than most cards being removed below. Either source a crop-specific
  mask, or relabel the card as generic cropland establishment and suppress
  `status` / `risk_label` until a crop mask exists. Do not ship it as-is.

### Do this before building any new card: keep the NDVI series

`_extract_ndvi_series()` (`snapshot.py:325`) already parses the Sentinel Hub
response into a per-interval list of NDVI means with their `interval.from`
dates — about eight points across the 40-day window at `P5D` — then discards all
of it and returns only the mean of the last three (lines 352–359).

Persist it as `sowing.ndvi_series: [{from, ndvi, coverage}]`. This is one already
paid-for API call. Do **not** implement "What Changed" as two Sentinel Hub calls
at t and t−14d, and do **not** implement the trajectory card as "repeated
Statistics calls over rolling windows" — both are several times more expensive
than simply not throwing away data you already fetched. The persisted series
gives you the trajectory card, the 14-day delta, and a real `weekly_rate_pp`
from one request.

### Tier 2 dispositions

Keep: **Weather / Moisture Context**. Note that
`WeatherContextClient.soil_moisture_and_temperature()` exists in
`app/services/connectors/weather.py:29` but `LiveSnapshotBuilder` never calls
it — only `rainfall_mm` is probed. So this card is one probe away, not already
wired. Add the probe, then render rainfall bars against a soil-moisture line.

Keep: **What Changed (14 days)** — from the persisted series, showing both
before and after NDVI values, not a bare delta.

Keep, move down from Tier 3: **Compare Mode** — two `LiveSnapshotBuilder.build()`
calls side by side. Genuinely free, and not an advanced feature.

Remove: **Normal vs Abnormal**, **Phenology Timing**, **Catch-Up Potential**,
**Historical Yield Anomaly**, **Forecast + Uncertainty**, **Attainable
Benchmark**, **Spatial Risk / Potential Contributors**, **Gap Waterfall**. All
need a historical baseline, a calibrated model, or price data. Do not replace any
of them with a synthetic band.

Replace **Historical Progress Curve** with **Recent NDVI Trajectory** — the
persisted 40-day series as a sparkline, labelled "recent trend" with no implied
multi-year context.

Remove **Crop Stage Distribution** and **Spatial Distribution** as currently
defined, but record in the commit message that these are *deferred, not
impossible*: the Sentinel Hub Statistical API supports histogram outputs, and a
sub-district grid can be derived from the district polygon itself (split the
bbox into 4×4, keep cells whose centroid is inside the polygon — point-in-polygon
is about fifteen lines in the same dependency-free style as the existing shoelace
code). Deferring is the right call for this commit; claiming they are
unreachable is not accurate.

Add: **Vegetation Vigor Trend** — Sentinel-2 NDVI and Sentinel-1 VH backscatter
plotted together for the same window, flagging optical/radar agreement or
disagreement. Two independent sensors cross-checking each other is a real result
that needs no baseline.

Add: **Rainfall–Vegetation Response** — CHIRPS rainfall lagged one to two weeks
against the NDVI trajectory, same geometry. Answers "is this region's vegetation
tracking its rainfall or decoupled from it" from two already-wired sources.

Add: **Crop-Type Composition** — WorldCereal cropland fraction multiplied by the
polygon's own area from `_estimate_admin_area_ha()`, rendered as a donut and
labelled land-cover composition, explicitly not production.

### Tier 1 and Tier 3

Remove `yield_current`, `yield_gap`, `production_economic` from Tier 1 outright —
do not demote them to Tier 2 with invented numbers. Fill the freed headline slot
with a **Vegetation Vigor Index**: one composite of recent NDVI and Dynamic World
crop probability on a 0–100 scale, labelled a condition proxy, never a yield
estimate.

Tier 3 keeps `evidence_stack`, `data_quality`, `lineage_trace`,
`know_dont_know` — pure metadata, already real. Remove
`spatial_autocorrelation` and `change_point_detection`; both need pixel-level or
multi-year series. (`change_point_detection` becomes feasible on the persisted
NDVI series later — note it, don't build it now.)

Report the final Tier 2 count and list. Do not pad it back to twelve.

## Commit 3 — Interpretation and visuals

Add `app/services/interpretation.py` with one function per indicator —
`interpret_ndvi(value) -> str`, and equivalents for soil moisture, rainfall, and
Dynamic World probability — reused by every card surfacing that indicator, never
copy-pasted per card. Bands must come from **published generic agronomic ranges**
with the citation in a docstring, never from a fabricated "this district's
normal range", which would reintroduce exactly the baseline fabrication this
redesign exists to remove. Carry a note that thresholds vary by crop and growth
stage.

**Charting decision, which the original prompt left open:** there is no chart
library in `app/static/` — only maplibre-gl. Recommendation: hand-roll inline
SVG helpers (sparkline, dual-axis line, donut, gauge, stacked bar). Sparklines
and gauges are a few dozen lines each, it adds no dependency, and it matches how
this repo already handles geometry math with its own shoelace implementation
rather than pulling in shapely. If you disagree, vendor uPlot (about 40 KB) into
`app/static/vendor/` in the same style as maplibre-gl — but decide and say which,
do not silently add a CDN `<script>` tag.

This commit depends on the Tier-2 plan already in
`docs/TIER2_CARD_PLAN.md` §4: the value binding must move into
`data/seed/card_manifest.json` as a `render` block, and the nine-branch
`card_id` switch in `cardHTML()` (`app/static/app.js:333`) must be deleted. Do
not add three more `if` branches for the three new cards — that is what produced
the current mess, where every unbound card falls through to
`JSON.stringify(val).slice(0, 140)`.

Keep interpretation text adjacent to each chart, not in a hover tooltip.

## Verification

`pytest`, with every connector mocked. Assert both the computed value and the
correct interpretation band per card.

Then load a real registered district end to end — Rajgarh
(`IND-ADMIN2-MADHYA-PRADESH-RAJGARH`) and Vidisha are both good, and Ludhiana is
now the interesting case because it has no fixture to fall back on. Confirm four
things: no fixture code path is reachable, every rendered card is one this audit
marked feasible, every removed card is genuinely absent rather than rendering
`null` or a placeholder, and every number on screen has interpretive text beside
it.

Report the diff summary: removed, added, modified.
