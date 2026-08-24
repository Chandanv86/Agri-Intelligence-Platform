# Production Implementation Plan — DEMO → LIVE

Author: Lead Data Engineer / Geospatial Systems Architect (Claude)
Scope: turns the current DEMO-only MVP (`snapshot.py` reading two static
fixtures) into a horizontally-scalable, credential-backed LIVE system that
serves any district/ward/woreda across all six countries, without ever
silently fabricating evidence. This plan assumes the codebase reviewed in
`docs/KNOWN_LIMITATIONS.md` and preserves its core invariant:

> **A snapshot is either backed by real evidence with `fired=True` sources,
> or it is explicitly `data_status: DEMO`/`501`. It is never something in
> between.**

Everything below is additive to that invariant, not a relaxation of it.

---

## 0. Current-state map (what exists today)

| Layer | State |
|---|---|
| `snapshot.py` | Synchronous, fixture-only (`_FIXTURE_FILES` dict of 2 entries) |
| `connectors/earth_engine.py`, `sentinelhub.py` | Real API contracts, lazy-imported, unauthenticated — correctly raise `*NotConfigured` |
| `connectors/amed.py` | Real contract, India-only, allowlist-gated |
| `connectors/worldcereal.py`, `weather.py` | Real contracts, depend on `EarthEngineConnector` |
| `geography.py` / `geography.json` | 192 admin-1 units (6 countries), 20 India admin-2 pilot units, no admin-3/4 |
| `country_adapters/*` | Clean per-country strategy seam (crop-mask source, price currency, rainfall source) — this is the right extension point, keep it |
| API | Fully synchronous FastAPI (`def`, not `async def`) — this is the biggest structural blocker to Phase 1 |
| Deployment | Single `Dockerfile` + one-service `docker-compose.yml`, no worker/queue/cache tier |

Five things must change structurally, independent of any single credential:
the request path must become **async-capable**, the snapshot builder must
become **connector-orchestrating instead of fixture-reading**, results must
be **cached** (GEE `reduceRegion` calls are too slow and too rate-limited to
recompute per click), geometry must **carry its own polygon**, not just an
`admin_id` string, and the datastore must move from **flat JSON files** to
**Postgres/PostGIS** once the district count goes from 20 to 700+.

---

## 1. Target architecture

```
                         ┌─────────────────────────────────────────┐
   Browser (MapLibre)    │                FastAPI (api)             │
   click admin_id ──────▶│  GET  /agri/areas/{id}/snapshot          │──┐
                         │       (crop_id, season_id)                │  │ cache hit?
                         └─────────────────────────────────────────┘  │
                                     │  cache miss                    │
                                     ▼                                │
                         ┌─────────────────────────────────────────┐  │
                         │  POST enqueue → Celery (Redis broker)    │◀─┘
                         │  task_id returned, 202 Accepted          │
                         └─────────────────────────────────────────┘
                                     │
                    ┌────────────────┼─────────────────┐
                    ▼                ▼                 ▼
             celery worker    celery worker      celery-beat
             (io-bound pool)  (io-bound pool)     (periodic: baselines,
             GEE / SentinelHub / AMED / WorldCereal  crosswalk refresh,
             connector calls, one task per          cache warm)
             (admin_id, crop_id, season_id, week)
                    │
                    ▼
        Postgres + PostGIS ────────────────────────────────────────
        - boundaries (admin_unit geometry, all tiers)
        - snapshot_cache (materialized AgriSnapshot JSON, TTL'd)
        - historical_baseline (per admin_id/crop/season "normal curve")
        - target_area (census / crop-mask denominators)
        - price_series (Agmarknet + other feeds)
        Redis ───────────────────────────────────────────────────────
        - Celery broker + result backend
        - short-TTL hot cache (last N clicked snapshots)
```

Key design decisions and why:

1. **Celery + Redis, not FastAPI `BackgroundTasks`.** GEE `.getInfo()` calls
   are synchronous, blocking, 10–30s, and rate-limited per project. That
   workload needs retry/backoff, concurrency control, and a dead-letter path
   — `BackgroundTasks` gives none of that and dies with the request process.
2. **Cache-first, task-on-miss.** A district's satellite-derived snapshot is
   valid for the observation cadence of the underlying sensor (Sentinel-2:
   ~5 days revisit at these latitudes), not per HTTP request. We cache the
   *materialized* `AgriSnapshot` keyed by `(admin_id, crop_id, season_id,
   iso_week)`, not just raw connector output, so a second click for the same
   week/place is instant.
3. **PostGIS, not more GeoJSON files.** 700+ India districts × future
   sub-district layers cannot stay as flat files checked into git or loaded
   into process memory per request the way `GeographyService` does today.
   PostGIS gets us spatial indexing (`ST_Contains`, `ST_Intersects`), which
   we need anyway for point-in-polygon target-area/price aggregation.

---

## 2. Phase 1 — Async task queue (Celery + Redis)

### 2.1 Task contract

```python
# app/workers/celery_app.py
from celery import Celery
celery_app = Celery(
    "agri_intel",
    broker=settings.celery_broker_url,   # redis://redis:6379/0
    backend=settings.celery_result_backend,  # redis://redis:6379/1
)
celery_app.conf.update(
    task_acks_late=True,               # survive worker crash mid-GEE-call
    worker_prefetch_multiplier=1,      # don't hoard slow IO tasks
    task_time_limit=120,               # hard kill runaway GEE calls
    task_soft_time_limit=90,
    result_expires=60 * 60 * 6,        # 6h — snapshots go stale anyway
    task_routes={
        "agri.build_snapshot": {"queue": "snapshot"},
        "agri.build_baseline": {"queue": "baseline"},   # separate queue: slow, batch
    },
)
```

```python
# app/workers/tasks.py
@celery_app.task(name="agri.build_snapshot", bind=True,
                  autoretry_for=(SentinelHubNotConfigured, EarthEngineNotConfigured),
                  retry_backoff=True, retry_kwargs={"max_retries": 0})
                  # ^ NotConfigured is NOT retried -- it's a config error, not
                  #   a transient one. Retry only httpx.HTTPStatusError / GEE
                  #   transient errors, listed separately below.
def build_snapshot_task(self, admin_id: str, crop_id: str, season_id: str):
    builder = LiveSnapshotBuilder()
    snap = builder.build(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
    cache.put(key=snapshot_cache_key(admin_id, crop_id, season_id), value=snap, ttl=...)
    return snap.model_dump(mode="json")
```

### 2.2 API contract change (backward compatible)

Keep the existing synchronous `GET /agri/areas/{admin_id}/snapshot` for the
DEMO/fixture-backed districts (Ludhiana/Patna) — no reason to add latency
where the answer is already instant. Add the LIVE path alongside it:

```
GET  /agri/areas/{admin_id}/snapshot?crop_id&season_id
     → 200 with cached snapshot (cache hit, DEMO fixture, or already-computed LIVE)
     → 202 {"task_id": "...", "status_url": "/tasks/{task_id}"} (cache miss, LIVE-capable)
     → 501 (cache miss, not LIVE-capable and no fixture — current behavior, unchanged)

GET  /tasks/{task_id}
     → 202 {"state": "PENDING"|"STARTED"}
     → 200 {"state": "SUCCESS", "snapshot": {...}}
     → 500 {"state": "FAILURE", "error": "..."}
```

Frontend change (`app.js`): on `202`, poll `/tasks/{task_id}` every ~2s
(exponential backoff to 10s) and show a "Computing live analysis for
{breadcrumb}…" state on the card — this is a small, contained frontend
change, not a rewrite.

### 2.3 Concurrency / rate-limit control

GEE and Sentinel Hub both rate-limit per project/account. Use Celery's
`worker_concurrency` **plus** a `redis`-backed semaphore inside the task
(e.g. `redis.py`'s `Redis().set(nx=True, ex=...)` token bucket) so multiple
worker replicas don't collectively exceed the quota — this is the standard
failure mode when scaling workers horizontally without a shared rate limiter.

### 2.4 Idempotency

Cache key = `sha256(admin_id, crop_id, season_id, iso_year_week, connector_version)`.
Two users clicking the same district in the same ISO week within TTL get the
same cached result and never double-enqueue — dedupe check happens **before**
`apply_async`, using `SETNX` on a `lock:{cache_key}` Redis key with the task's
own soft-time-limit as the lock TTL.

---

## 3. Phase 2 — Wiring real connectors into `snapshot.py`

`snapshot.py` currently has exactly one code path: `_load_fixture`. Replace
this with a strategy that **keeps the fixture path for the 2 pilot
districts** (do not regress the tested, deterministic DEMO experience) and
adds a `LiveSnapshotBuilder` for everything else:

```python
class SnapshotSource(str, Enum):
    FIXTURE = "fixture"
    LIVE = "live"

class SnapshotOrchestrator:
    def resolve_source(self, admin_id, crop_id, season_id) -> SnapshotSource:
        if admin_id in _FIXTURE_FILES:
            return SnapshotSource.FIXTURE
        if settings.is_live_capable():
            return SnapshotSource.LIVE
        raise NoFixtureAvailable(...)   # unchanged 501 behavior

    def get_snapshot(self, *, admin_id, crop_id, season_id):
        src = self.resolve_source(admin_id, crop_id, season_id)
        if src is SnapshotSource.FIXTURE:
            return self._demo_service.get_snapshot(...)   # existing code, untouched
        return self._live_builder.build(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
```

`LiveSnapshotBuilder.build()` does the orchestration the connectors were
already written for but never called end-to-end:

1. `geometry = GeographyService.geometry_for(admin_id)` (needs Phase 5 —
   currently `GeographyService` returns attributes, not a polygon; this is
   the concrete blocker, see §5.4).
2. Fan out **concurrently** (not sequentially — this is the single biggest
   latency win) to:
   - `SentinelHubStatisticsClient.statistics(...)` — NDVI time series
   - `EarthEngineConnector.dynamic_world_crop_probability(...)`
   - `EarthEngineConnector.sentinel1_vh_backscatter_stats(...)`
   - `WeatherContextClient.rainfall_mm(...)` / `.soil_moisture_and_temperature(...)`
   - `AmedClient.field_crop_predictions(...)` if `adapter.supports_field_level_crop_source()`
   - `WorldCerealClient.crop_extent(...)` otherwise
3. Each call is wrapped individually — **a single connector failing must
   degrade that one `SourceRef.fired=False` and lower `confidence`, not
   fail the whole snapshot.** This mirrors the honesty principle already in
   `_sources()`; it just needs to apply per-connector instead of
   per-mode.
4. Feed the aggregated readings into the **existing, unmodified**
   `analytics/sowing.py`, `analytics/yield_gap.py`, `analytics/confidence.py`
   — those modules already take primitive floats, not fixture dicts, so
   they need zero changes. This is a major point in the current codebase's
   favor: the math layer was built decoupled from the fixture layer.
5. `expected_progress_pct` and `historical_expected_yield_kg_ha` come from
   the **Phase 3 baseline table**, not the fixture — this is the one place
   the LIVE path cannot simply mirror the DEMO path 1:1, because DEMO
   hardcodes these as fixture fields.

Since the GEE/httpx SDKs used here are blocking, Celery tasks run them
directly (Celery workers are separate processes — blocking I/O there does
not block the FastAPI event loop). Use `asyncio.gather` only for the
`httpx`-based calls (`sentinelhub.py`, `amed.py`); wrap the `ee`-based calls
(`earth_engine.py`, `weather.py`, `worldcereal.py`) with
`asyncio.to_thread(...)` if you want them concurrent with the httpx calls
inside the same task, or simply call them sequentially inside the Celery
task — either is fine since the task itself already runs off the request
thread.

### 3.1 Credential provisioning (step "a" from the prompt) — checklist, not code

| Provider | What's needed | Lead time note |
|---|---|---|
| Copernicus Data Space Ecosystem | OAuth2 client-credentials app (free registration) → `SENTINELHUB_CLIENT_ID/SECRET` | Self-service, ~same day |
| Google Earth Engine | Cloud project with Earth Engine API enabled + service account JSON, registered for **non-commercial or commercial** EE access per Google's current terms | Self-service for project registration; commercial tier may need a sales conversation — verify current terms before committing a timeline |
| Google AMED | GWCID allowlisting, India-only | **Not self-service** — requires Google approval; treat as a >2-week external dependency and do not block India-district launch on it (WorldCereal fallback already exists in the adapter for this exact reason) |

Store all three in a secrets manager (see §7), never in `.env` committed to
the repo — `.env.example` stays a template only, which the codebase already
gets right.

---

## 4. Phase 3 — Historical baseline pipeline

`expected_progress_pct` and `historical_expected_yield_kg_ha` are the two
fixture fields that cannot be replaced by a single live GEE call — they
require a **time-series baseline**, computed offline, not on the request
path.

### 4.1 Design

- **`celery-beat`** periodic task (`app/workers/beat_schedule.py`), runs
  monthly per country (staggered, not all at once — respects the same rate
  limiter as §2.3):
  ```python
  build_baseline_task.delay(country_id="IND")
  ```
- For each `(admin_id, crop_id, season_id)` combination known in
  `geography.json` × `crops.json` × `seasons.json`:
  - Pull 5–10 years of NDVI/Dynamic-World time series for that geometry
    from GEE (this is exactly what `earth_engine.py` already supports via
    `date_from/date_to` — just called in a loop over historical windows).
  - Fit a smoothed **day-of-season progress curve** (the "expected % sown by
    day N" curve). A simple, defensible starting model: per-week median
    across years, monotonic-smoothed (isotonic regression) — resist the
    urge to reach for something fancier before the simple baseline is
    validated against the 2 known-good pilot districts.
  - Fit an **expected/attainable yield distribution** the same way, using
    whatever historical yield proxy is available per country (national crop
    statistics office data where it exists; NDVI-integral-to-yield
    regression as a documented, lower-confidence fallback where it doesn't
    — and say so in `confidence.components`, don't hide it).
- Write results to `historical_baseline` table in Postgres:
  `(admin_id, crop_id, season_id, day_of_season, expected_progress_pct,
  expected_yield_kg_ha, source, computed_at, sample_years)`.
- `LiveSnapshotBuilder` reads this table (a fast indexed Postgres lookup,
  not a GEE call) at request time.

### 4.2 Cold-start handling

A newly-onboarded district has no baseline until the monthly job runs for
it. `LiveSnapshotBuilder` must handle "geometry registered, live NDVI
available, no baseline yet" as its **own explicit state** — not a silent
zero — analogous to how the fixture layer already distinguishes "unlinked
boundary" (404) from "no fixture" (501). Suggested: `data_status: "LIVE_NO_BASELINE"`,
still returns detected-area and confidence, omits `expected_progress_pct`/
`deviation` rather than fabricating them, and the frontend shows "insufficient
history for this district yet" instead of a false number.

---

## 5. Phase 4 — Target area & price data

### 5.1 Target area (denominator for sowing progress %)

Priority order per the existing adapter seam (`crop_mask_primary_source()` /
`crop_mask_fallback_source()`, already correct — extend it, don't replace
it):

1. **Government census** where available and machine-readable (India: DES/
   Agricultural Statistics at a Glance, district-level normal sown area).
   Ingested as a one-time/annual batch load into a `target_area` table, not
   fetched live.
2. **AMED-derived crop mask area** (India only, when allowlisted) —
   `amed.py`'s existing per-cell predictions aggregated over the admin
   polygon via PostGIS `ST_Intersects`.
3. **WorldCereal crop-type mask area** (all countries, already wired in
   `worldcereal.py`) — sum of "temporarycrops" pixel area within the
   polygon, computed in the same Celery task as the NDVI pull.

Each district's `AgriSnapshot` should record **which of these three tiers**
supplied its target area (`target_area_source` field) — this directly feeds
`confidence.components` and is exactly the kind of provenance this codebase
already insists on elsewhere.

### 5.2 Price data

- **India:** Agmarknet publishes modal mandi prices; no clean public REST
  API exists as of the current build, so this needs a scheduled scraper/ETL
  (respecting Agmarknet's terms of use) into the `price_series` table, not a
  live per-request call — prices update daily at most, so daily batch is
  sufficient and far more reliable than scraping on the request path.
- **Kenya/Uganda/Tanzania/Ethiopia/South Africa:** no single reliable source
  equivalent to Agmarknet exists today. Plan: FAO GIEWS and national
  Ministry of Agriculture bulletins as lower-frequency, lower-confidence
  fallbacks, explicitly reflected in `price_granularity_note()` (the adapter
  method already exists for exactly this purpose — §7 of
  `KNOWN_LIMITATIONS.md` flags this as a known weaker area; this plan
  doesn't paper over it, it batch-ingests what's actually publishable and
  lets the confidence model discount the rest).

---

## 6. Phase 5 — Boundary geometry depth

### 6.1 Data sourcing (per country, matching the prompt's asks)

| Country | Current depth | Next tier | Source |
|---|---|---|---|
| India | District (admin-2), all 35 states | Sub-district (admin-3) → Village (admin-4) | `data.gov.in` LGD (Local Government Directory) API for admin-3 codes/names; ISRO Bhuvan or state e-governance portals (varies by state) for village polygons — **expect this to be the least uniform source in the whole plan; budget per-state normalization, not one script** |
| Kenya | Legacy 8 provinces only (real geometry); 47 counties known as names/crosswalk, no polygons | 47 counties (real geometry) → constituencies → wards | IEBC (Independent Electoral and Boundaries Commission) shapefiles, or Kenya Open Data Portal |
| Uganda | Admin-1 (districts), geometry mismatched to registry per KNOWN_LIMITATIONS §3 | Fix admin-1 alignment first, then county/sub-county | UBOS (Uganda Bureau of Statistics) — also the authoritative source for the placeholder region→district crosswalk flagged in §4 of KNOWN_LIMITATIONS; fetch both in the same pass since they're the same authority |
| Tanzania | Region only | District → Ward | OCHA HDX Tanzania admin boundaries dataset |
| Ethiopia | Region only, **known stale** (pre-2020 Sidama split) | Do not deepen until admin-1 is fixed | OCHA HDX or Ethiopia Central Statistical Agency — this blocks on itself per KNOWN_LIMITATIONS §5; sequence it before, not alongside, any Ethiopia depth work |
| South Africa | Province (admin-1) | District municipality → Local municipality | South Africa MDB (Municipal Demarcation Board) |

### 6.2 Pipeline

`scripts/fetch_boundaries.py` already exists as the intended entry point —
extend it, don't replace it, following its existing per-source function
pattern:

1. Fetch raw shapefile/GeoJSON per source above.
2. Reproject to WGS84 if not already (the existing script's docstring
   references a "real projection bug that was caught and fixed" — add a CRS
   assertion test so that class of bug can't silently recur).
3. Simplify geometry for map rendering (`mapshaper` or `shapely.simplify`,
   topology-preserving) — keep a **full-precision copy in PostGIS** for
   `ST_Intersects` area calculations, and a **simplified copy** for the
   MapLibre vector layer; conflating these two is a common source of "area
   doesn't match what you'd expect from the map" bug reports.
4. Load into `boundaries` table (PostGIS `geometry(MultiPolygon, 4326)`,
   GiST-indexed) with `(admin_id, admin_level, country_id, source,
   source_version, fetched_at)`.
5. Run `scripts/validate_geography_counts.py` and
   `scripts/validate_crosswalk.py` (both already exist and already fail CI
   on mismatch — keep using them as the gate, just point them at the DB
   instead of the JSON file once Phase 6 lands).
6. Register new `admin_id`s into `geography.json`'s DB-backed successor
   (§7) — this is what actually fixes the "Unlinked Boundary" (Dantewada)
   error class: it exists *because* the polygon shipped in
   `static/boundaries/` but no registry entry was ever created for it. Any
   new boundary fetch **must** write the registry row in the same
   transaction as the geometry row, or this bug class reappears at the next
   admin level down.

---

## 7. Phase 6 — Tier 1/2/3 data architecture

Define the tiers explicitly (this codebase doesn't yet name them, which is
itself part of why "anomalies" like the mismatched Tanzania admin-1 count
(31 supplied vs 30 expected, already flagged in `geography.json`'s own
`data_quality_notes`) don't have an agreed place to be resolved):

- **Tier 1 — Registry** (`boundaries` + `admin_units` tables): the
  authoritative list of what places exist, their hierarchy, and their
  geometry. Source of truth for "is this a real place" (fixes Dantewada-class
  errors). No agricultural data lives here.
- **Tier 2 — Evidence** (`snapshot_cache`, `historical_baseline`,
  `target_area`, `price_series`): derived, connector-sourced data, always
  versioned and timestamped, always carrying a `data_status`. This is what
  Phases 2–4 populate.
- **Tier 3 — Presentation** (`card_manifest.json`'s existing renderable-card
  logic, unchanged): pure view-layer filtering of Tier 2 data — this layer
  is already correctly decoupled in the current codebase and needs no
  architectural change, just more Tier 2 data flowing into it.

### 7.1 Schema sketch (Postgres + PostGIS)

```sql
CREATE TABLE admin_units (
    admin_id            TEXT PRIMARY KEY,
    country_id          TEXT NOT NULL,
    admin_level         INT NOT NULL,
    parent_admin_id     TEXT REFERENCES admin_units(admin_id),
    canonical_name      TEXT NOT NULL,
    merged_into         TEXT REFERENCES admin_units(admin_id),
    source              TEXT NOT NULL,
    source_version      TEXT NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE boundaries (
    admin_id            TEXT PRIMARY KEY REFERENCES admin_units(admin_id),
    geom_full           geometry(MultiPolygon, 4326) NOT NULL,
    geom_simplified     geometry(MultiPolygon, 4326) NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL
);
CREATE INDEX boundaries_geom_gix ON boundaries USING GIST (geom_full);

CREATE TABLE snapshot_cache (
    cache_key           TEXT PRIMARY KEY,   -- sha256(admin_id, crop_id, season_id, iso_week)
    admin_id            TEXT NOT NULL REFERENCES admin_units(admin_id),
    crop_id             TEXT NOT NULL,
    season_id           TEXT NOT NULL,
    iso_year_week       TEXT NOT NULL,
    payload             JSONB NOT NULL,     -- the AgriSnapshot, as-served
    data_status         TEXT NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL
);

CREATE TABLE historical_baseline (
    admin_id            TEXT NOT NULL REFERENCES admin_units(admin_id),
    crop_id             TEXT NOT NULL,
    season_id           TEXT NOT NULL,
    day_of_season       INT NOT NULL,
    expected_progress_pct     NUMERIC,
    expected_yield_kg_ha      NUMERIC,
    source               TEXT NOT NULL,
    sample_years          INT NOT NULL,
    computed_at            TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (admin_id, crop_id, season_id, day_of_season)
);

CREATE TABLE target_area (
    admin_id TEXT NOT NULL REFERENCES admin_units(admin_id),
    crop_id TEXT NOT NULL, season_id TEXT NOT NULL,
    target_area_ha NUMERIC NOT NULL,
    source TEXT NOT NULL,     -- 'census' | 'amed' | 'worldcereal'
    as_of DATE NOT NULL,
    PRIMARY KEY (admin_id, crop_id, season_id, source)
);

CREATE TABLE price_series (
    admin_id TEXT NOT NULL REFERENCES admin_units(admin_id),
    crop_id TEXT NOT NULL,
    price_date DATE NOT NULL,
    price_value NUMERIC NOT NULL, price_unit TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (admin_id, crop_id, price_date, source)
);
```

### 7.2 Anomaly handling policy

Every anomaly class already named in this codebase gets an explicit,
queryable home instead of a comment:

| Anomaly | Current handling | DB-backed handling |
|---|---|---|
| Unlinked boundary (Dantewada) | Runtime check against `_by_id` dict | `boundaries` row exists, `admin_units` row missing → nightly `orphaned_boundaries` audit query, alerts instead of surfacing only on user click |
| Admin-1 count mismatch (Tanzania 31 vs 30) | `data_quality_notes` field, static text | `admin_units` row gets `count_status='mismatch'` + `notes`; `validate_geography_counts.py` becomes a scheduled CI job against the DB, not a one-off script |
| Legacy province → real unit crosswalk (Kenya) | `geography_crosswalk.json` | `crosswalk_groups` table, same shape, DB-backed so it can be queried/joined instead of loaded whole into memory |
| Placeholder crosswalk (Uganda) | Explicit placeholder string, fails CI | Same rule, DB-enforced via a `NOT NULL CHECK (mapping_status != 'placeholder')` constraint on a production-flagged environment, so a placeholder literally cannot ship to prod even if someone forgets to run the validator |
| Stale admin-1 (Ethiopia) | `ethiopia_boundary_staleness_flag` in crosswalk JSON | `admin_units.source_version` + a `superseded_by_pending_source` boolean; adapter registry checks this flag and keeps Ethiopia out of the LIVE country list until cleared — same behavior, just enforced in one place instead of relying on every caller remembering to check |

### 7.3 Migration path (JSON → Postgres)

Keep `GeographyService`'s **public method signatures** unchanged
(`resolve`, `children`, `admin1_for_country`, `crosswalk_groups`, …) and
swap its internals from JSON-file reads to SQLAlchemy queries. This means
`geography_match.py`, `routes.py`, and every test that calls
`GeographyService` through its public interface needs **zero changes** —
only `geography.py`'s `__init__` and method bodies change. Use `alembic` for
schema migrations, and write a one-time `scripts/migrate_geography_json_to_db.py`
that loads the existing `geography.json`/`geography_crosswalk.json` as the
initial seed (so this is additive, not a rewrite-and-hope-nothing-broke).

---

## 8. Rollout plan (prioritized, matches the prompt's stated priority: dynamic pipeline over manual entry)

| Phase | Deliverable | Unblocks |
|---|---|---|
| **P0** | Dockerize (this response) — Redis, Postgres, worker, beat, flower services scaffolded and runnable in DEMO mode with zero live credentials | Every later phase; also de-risks "does the infra even come up" before any GEE credential exists |
| **P1** | Celery task queue live, `LiveSnapshotBuilder` wired to real connectors for a **single already-registered district** (pick one more than the existing 2, e.g. an India district with a real `admin_id`) behind a feature flag | Proves the full async request→task→connector→cache round trip end-to-end before scaling to 700 |
| **P2** | Postgres/PostGIS migration of `geography.json` (§7.3) — this is a prerequisite for both target-area PostGIS queries and for loading >20 admin-2 units without inflating process memory | All district-scale work |
| **P3** | Historical baseline batch job (§4) for India districts with existing registry entries | Removes the "LIVE_NO_BASELINE" degraded state for India |
| **P4** | Boundary depth fetch for India admin-3 (§6) — highest population/user-value payoff given India is the only country with an MVP pilot today | Fixes remaining India "Unlinked Boundary" errors within India, at whatever depth is fetched |
| **P5** | Repeat P3/P4 pattern per additional country, in this order: Kenya (counties already crosswalk-mapped, just need polygons) → South Africa → Tanzania → Uganda (blocked on UBOS crosswalk, §4 of KNOWN_LIMITATIONS) → Ethiopia (blocked on stale admin-1 fix first) | Full 6-country LIVE coverage |
| **P6** | Price/target-area batch ETL (§5) | Removes remaining fixture-only numeric fields |

This order deliberately does **not** try to onboard all 6 countries or all
700+ districts simultaneously — it proves the pipeline on a small, known-good
slice first (matching the same "prove it end-to-end on Ludhiana/Patna before
scaling" instinct the current MVP itself used), then scales district count
and country count as two independent, parallelizable axes once the pipeline
itself is validated.

---

## 9. Observability & ops (needed the moment Celery exists)

- **Flower** (bundled in the compose file below) for live task
  inspection — essential once tasks can silently pile up in a queue.
- Structured logging: every task logs `cache_key`, `admin_id`,
  `connectors_attempted`, `connectors_fired`, `duration_ms` — this is the
  natural extension of the `SourceRef.fired` honesty pattern already in the
  code, just logged as well as returned.
- Alert on: queue depth growing unbounded, `NoFixtureAvailable`/`501` rate
  spiking (signals a boundary/registry gap, same as the Dantewada case),
  and connector error rate per provider (signals a credential or quota
  problem before users notice degraded confidence scores).
- Add a `/health/deep` endpoint that checks Redis, Postgres, and
  (non-blocking) whether each configured connector's credentials are still
  valid — cheap to build, catches "credentials expired" before a user does.

---

## 10. What this plan deliberately does not do yet

- It does not pick a final commercial-vs-non-commercial GEE licensing tier —
  that's a legal/commercial decision, not an engineering one, and terms
  change; confirm current terms directly with Google before committing.
- It does not attempt Ethiopia depth work before the admin-1 staleness issue
  is resolved, per the existing `unresolved_blocker_for_ethiopia_v1` flag —
  building on top of known-wrong boundaries would just move the bug deeper
  into the stack.
- It does not replace the 2 existing DEMO fixtures — they remain the fast,
  deterministic path for demos/tests, and are a useful regression check
  ("does Ludhiana's LIVE number land in the same ballpark as its DEMO
  fixture") once Ludhiana itself is eventually promoted to LIVE.
