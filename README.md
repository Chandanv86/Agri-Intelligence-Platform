# Agricultural Intelligence Platform

Hierarchy-aware Sowing Progress + Yield Gap intelligence across India, Kenya,
Uganda, Tanzania, Ethiopia, and South Africa. Click an administrative unit,
get a snapshot of two analytical themes rendered as a tiered, 32-card stack.

**Read `docs/KNOWN_LIMITATIONS.md` first.** This build runs entirely in DEMO
mode with two real Indian districts (Ludhiana, Patna) wired to fixture data —
it is an architecture-and-analytics-correct MVP skeleton, not a live product.
See `docs/ARCHITECTURE.md` for the design, `docs/BOUNDARY_DATA_SOURCES.md`
for exactly where the real map geometry comes from (and a real projection
bug that was caught and fixed while sourcing it), and
`docs/KNOWN_LIMITATIONS.md` for everything else that is and isn't real here.

## What you'll see

A real, clickable 3D globe (MapLibre GL, vendored locally — no CDN
dependency, no API key). Click a highlighted country, it flies in and shows
real state/province/region/county boundaries; for India, click a state and
real district boundaries load; click a district with a live fixture
(Ludhiana in Punjab, Patna in Bihar) and the full 32-card tiered analytical
panel renders. Click anywhere else and the app says plainly that there's no
live snapshot there yet, instead of inventing one.

## Quickstart

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

Try it: click the globe → India → Punjab → Ludhiana. (Bihar → Patna also
works.) Everywhere else in the six-country hierarchy is real and clickable
but will show "no live snapshot yet" — see docs/KNOWN_LIMITATIONS.md.

## Tests

```bash
pytest tests/ -v          # 78 tests: math, aggregation, geography, cards, API, boundary-data integrity
python scripts/validate_geography_counts.py
python scripts/validate_crosswalk.py   # exits 1 until Uganda crosswalk is real
```

## Layout

```
app/
  core/config.py            # env-driven settings, LIVE-mode gate
  schemas/                  # pydantic contracts (DataStatus, Confidence, Lineage, ...)
  services/
    geography.py            # crosswalk resolution, merge/depth rules
    catalog.py               # crops + multi-season calendars
    card_manifest.py         # loads/filters the 32-card manifest
    snapshot.py               # THE unified orchestrator -- one snapshot per click
    country_adapters/         # per-country hierarchy/pricing/source rules
    analytics/                 # sowing, yield_gap, confidence, lineage, aggregation, spatial_stats
    connectors/                 # Sentinel Hub, CDSE STAC, GEE, AMED, weather, WorldCereal
  api/routes.py               # FastAPI endpoints
  static/
    app.js, app.css, boundaries/   # real WGS84 GeoJSON: world + 6 countries' admin1 + India's 35 states' districts
    vendor/maplibre-gl/             # MapLibre GL JS, vendored (no CDN dependency)
  templates/                    # index.html: globe intro + full-bleed map + slide-in card panel
data/seed/                    # geography, crosswalk, crops, seasons, card manifest
data/examples/                # deterministic demo fixtures (Ludhiana, Patna)
scripts/                      # validation + documented (not-yet-runnable) boundary ingestion
tests/                        # 60 unit + integration tests
docs/                         # ARCHITECTURE.md, KNOWN_LIMITATIONS.md
```

## Going from DEMO to LIVE

1. Fill in `.env` (copy from `.env.example`): Sentinel Hub / CDSE OAuth
   credentials, GEE service account + project, optionally AMED key (India only,
   requires Google allowlisting).
2. Replace `SnapshotService._load_fixture` with real connector calls
   (`services/connectors/*`) gated on `Settings.is_live_capable()`.
3. Run `scripts/fetch_boundaries.py` from an environment with open network
   access to ingest real GADM/HDX polygons; this sandbox cannot reach them.
4. Close the two open crosswalk items in `docs/KNOWN_LIMITATIONS.md` (§4, §5)
   before enabling Uganda/Ethiopia.
