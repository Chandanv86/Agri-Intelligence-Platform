# Tier-2 Cards — Region-Agnostic Fix Plan

Written 2026-08-23 against the live Rajgarh output (`IND-ADMIN2-MADHYA-PRADESH-RAJGARH`,
rice, `IND-2026-kharif-rice`). Nothing below is Rajgarh-specific: the same three
defects fire for Vidisha, Ludhiana, Patna and every district added later.

## 1. What is actually wrong

There are three separate defects, and it matters that they are separate, because
only one of them is a rendering bug.

**Defect 1 — the renderer has no binding for Tier-2 cards.** `cardHTML()`
(`app/static/app.js:333`) is an `if / else if` chain over exactly nine
`card_id` values. Every other card falls through to the catch-all at line 374:

```js
} else if (val && typeof val === "object") {
  subLine = JSON.stringify(val).slice(0, 140);
}
```

Eight Tier-2 cards declare `snapshot_path: "sowing"` — the *entire* sowing
object — so all eight stringify the same object and truncate at 140 characters.
That is why every card shows the identical
`{"country_id":"IND","admin_id":"IND-ADMIN2-MADHYA-PRADESH-RAJGARH","crop_id":"rice",…`
string. Ludhiana behaves exactly the same way; it goes unnoticed there only
because Tier 2 is collapsed by default and Tier 1 looks healthy.

**Defect 2 — `requires: []` means "always render", so evidence-free cards render
anyway.** `CardManifestService.renderable_cards()` drops a card when any path in
its `requires` list resolves to `null`, `[]` or `{}`. Twelve of the 32 cards
declare `requires: []`, which is not a gate at all — it is an unconditional
pass. Spatial Risk Distribution and Potential Contributors both point at
`yield_performance`, which LIVE mode sets to `None` on purpose (a yield gap
needs attainable and historical-expected baselines that do not exist yet), so
`String(null)` renders the literal text `null`. This is the worst of the three
defects: a card that says `null` implies the system tried and found nothing,
when the truth is that the pipeline behind it was never built.

**Defect 3 — Crop Stage Distribution is real, but saturated.**
`{"established":100,"emerging":0,"not_detected":0,"uncertain":0}` is not a
placeholder. Live establishment comes from
`established_frac = (ndvi - 0.15) / 0.30` clamped to 0–1 (`snapshot.py:655`), so
any NDVI at or above 0.45 pins it to 100%. Rajgarh in late August is a closed
canopy, so it saturates. `emerging` is hardcoded `0.0` because there is no
per-pixel stage classifier on the live path, and `uncertain = (1 - coverage) *
100` is 0 because coverage was complete. The card is honest about its inputs,
but the proxy has no headroom left and rendering it as raw JSON hides both
facts from the reader.

## 2. The contradiction to fix first

The manifest's own header claims:

> The frontend renders purely from this manifest -- tiering/ordering is data,
> not frontend code.

Tiering and ordering *are* data. Value rendering is **not** — it is a `card_id`
switch in JavaScript. That single inconsistency is why "make Tier 2 work for
every region" is currently a JS task rather than a data task. Moving the value
binding into the manifest is what makes a card work for Rajgarh, Vidisha,
Ludhiana and any district added next week without anyone touching `app.js`.

## 3. Phase 0 — stop rendering nulls (~15 min)

Replace every `requires: []` with the dotted paths the card genuinely needs, and
add a `dark_reason` string alongside. Then extend `renderable_cards()` to return
two lists instead of one: the cards whose gate passed, and the cards whose gate
failed together with their reason. `app.js` renders the second list as dimmed
tiles reading "Not available yet — needs {reason}".

The gate is evaluated against the snapshot that was just built, so this is
region-agnostic by construction: a district where Sentinel-2 fired shows more
cards than one where only CHIRPS fired, with no per-district configuration.

After this phase, no card anywhere can show `null` or a raw JSON dump. Some
cards will disappear from Tier 2 and reappear as honest placeholders — that is
the intended outcome, not a regression.

## 4. Phase 1 — manifest-driven value binding (~45 min)

Give each card a `render` block. For a scalar:

```json
{"card_id": "sowing_trend", "render": {
  "kind": "number", "value_path": "sowing.weekly_rate_pp",
  "unit": "pp/wk", "precision": 2,
  "sub": [{"label": "Status", "path": "sowing.status", "transform": "humanize"}],
  "status_path": "sowing.data_status"}}
```

For a distribution:

```json
{"card_id": "sowing_stage_distribution", "render": {
  "kind": "stacked_bar", "series_path": "sowing.stage_distribution", "unit": "%"}}
```

Then rewrite `cardHTML()` as a dispatch on `render.kind` — `number`, `table`,
`stacked_bar`, `bar`, `line_envelope`, `matrix`, `waterfall` — reading only the
bindings. Each of the nine hardcoded branches becomes a binding and the switch
is deleted. Adding or re-pointing a card becomes a JSON edit.

## 5. Phase 2 — keep the NDVI series; it unlocks five cards for free (~2–3 h)

This is the highest-leverage change in the plan and it needs no new connector.

`_extract_ndvi_series()` (`snapshot.py:325`) already parses the Sentinel Hub
Statistics response into a per-interval list of NDVI means with their
`interval.from` dates — roughly eight points across the 40-day window at
`P5D` aggregation — and then discards all of it, returning only the mean of the
last three (`snapshot.py:352-359`). Persist the series as
`sowing.ndvi_series: [{from, ndvi, coverage}]` and the following become real:

Sowing Trend gets an actual `weekly_rate_pp` from the slope of establishment
over the last two weeks, instead of the hardcoded `0.0` at `snapshot.py:738`.
What Changed (14 days) becomes the difference between the last two 7-day chunks
of the same series, with no historical table involved. Change Detection becomes
a within-season breakpoint test on that series. Phenology Timing becomes the
date of the steepest NDVI rise, which is an observed green-up date — DERIVED and
defensible without any baseline. And the progress curve can plot the observed
within-season trajectory immediately, leaving only the multi-year envelope for
Phase 4.

## 6. Phase 3 — a sub-district grid makes the three spatial cards real (~2–3 h)

The repo carries admin2 polygons only, so there is nothing below district level
to aggregate — which is why the spatial cards have no data source rather than a
broken one. But `SentinelHubStatisticsClient` already accepts an arbitrary bbox
and `resolution_for_bbox()` already scales resolution to AOI size, so the
missing input can be generated from the polygon itself.

Split the district bbox into a 4×4 grid, keep only cells whose centroid falls
inside the polygon (point-in-polygon is about fifteen lines, no geo dependency,
the same style as the existing shoelace area code), and run NDVI statistics per
surviving cell. That yields a genuine observed spatial distribution across the
district, which fills Spatial Distribution, Where Is It Happening and Spatial
Risk Distribution — labelled DERIVED, with the caveat "equal-area grid cells,
not administrative sub-units" carried on the card. Because the grid is derived
from whatever polygon `geometry_for()` returned, it works for any district in
any state with no lookup table.

## 7. Phase 4 — cards blocked on the historical baseline table

Historical Progress Curve (the envelope), Normal vs Abnormal, Historical Yield
Anomaly, Forecast + Uncertainty Interval, Attainable Benchmark, Seasonal vs
Structural Gap, Economic Sensitivity and every card reading `yield_performance`
need multi-year per-district baselines — section 4 of
`docs/PRODUCTION_IMPLEMENTATION_PLAN.md`. Until that table exists these stay
dark with a reason string. Inventing the baselines to light the cards would
violate the demo-versus-live rule, which is the one rule this codebase is built
around.

Still open from the previous session and worth deciding in the same pass:
`target_area_ha` on the live path derives from a **generic** cropland fraction
(Dynamic World crop probability, or WorldCereal `temporarycrops`), not a
rice-specific mask. Comparing NDVI-derived establishment against the rice
calendar therefore produces deviation, status and risk labels that overstate the
evidence. Either add a crop-specific mask or relabel those three fields honestly
before anyone trusts them.

## 8. Per-card disposition

| Card (Tier 2) | Renders today | Fix phase |
| --- | --- | --- |
| Historical Progress Curve | JSON dump | 2 (observed curve) + 4 (envelope) |
| Phenology Timing | JSON dump | 2 — steepest NDVI rise date |
| Crop Stage Distribution | raw JSON, saturated at 100 | 1 — stacked bar; note the proxy ceiling |
| Catch-Up Potential | JSON dump | 1 — `analytics/sowing.catch_up_days` already exists and is imported |
| Spatial Distribution | JSON dump | 3 — grid |
| Weather / Moisture Context | JSON dump | 1 — CHIRPS is already in `sowing.confidence.components.rainfall_mm_window`; promote it to a first-class `weather_context` block so the path is stable |
| Historical Yield Anomaly | gated off (correct) | 4 |
| Forecast + Uncertainty Interval | JSON dump | 4 |
| Attainable Benchmark | gated off (correct) | 4 |
| Spatial Risk Distribution | literal `null` | 0 (gate) then 3 |
| Potential Contributors | literal `null` | 0 (gate) then 4 |
| Seasonal vs Structural Gap | gated off (correct) | 4 |
| What Changed (14 days) | JSON dump | 2 |
| Where Is It Happening | JSON dump | 3 |
| Normal vs Abnormal | JSON dump | 4 |

## 9. What "every region" still cannot mean

One genuine per-region limit survives all four phases. `geometry_for()` resolves
India admin-level-2 units only, by matching `NAME_2` inside a bundled
`app/static/boundaries/india_districts/<state-slug>.geojson`. Selecting a state,
a country, or anything outside India still raises `GeometryNotAvailable` → HTTP
422, and no amount of card work changes that. Broadening boundary coverage is a
separate task from card rendering and should not be folded into this plan.
