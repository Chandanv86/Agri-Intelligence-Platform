"""The unified analytical snapshot service. §3 of the review doc: this is the
ONE place that assembles sowing + yield + confidence + lineage + data-status
into a single AgriSnapshot. Cards never independently call sowing/yield
endpoints -- they all read from what this service produces."""

import asyncio
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from ..core.config import settings
from ..schemas.common import (
    Confidence, ConfidenceClass, DataStatus, Deviation, Freshness,
    Lineage, SourceRef, SpatialSupport, UncertaintyRange,
)
from ..schemas.agriculture import (
    SowingProgressResponse, YieldPerformanceResponse, CropsGrownHereEntry,
)
from ..schemas.snapshot import AgriSnapshot, Identity, AgriculturalSituation
from .analytics.sowing import calculate_sowing_progress, stage_distribution, catch_up_days
from .analytics.yield_gap import calculate_yield_impact
from .analytics.confidence import confidence_score, confidence_label, penalize_for_staleness
from .analytics.lineage import make_trace_id, make_snapshot_id, now_utc
from .geography import GeographyService
from .country_adapters.registry import get_adapter

_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "examples"

_FIXTURE_FILES = {
    "IND-ADMIN2-PUNJAB-LUDHIANA": "demo_fixture_punjab_rice_kharif.json",
    "IND-ADMIN2-BIHAR-PATNA": "demo_fixture_bihar_rice_kharif.json",
}


class NoFixtureAvailable(LookupError):
    pass


class SnapshotService:
    def __init__(self, geography: GeographyService | None = None):
        self.geography = geography or GeographyService()

    # ---- fixture-backed DEMO path --------------------------------------
    def _load_fixture(self, admin_id: str) -> dict:
        fname = _FIXTURE_FILES.get(admin_id)
        if not fname:
            raise NoFixtureAvailable(
                f"No demo fixture for {admin_id}. MVP scope currently covers "
                f"{list(_FIXTURE_FILES)} only (see docs/KNOWN_LIMITATIONS.md)."
            )
        return json.loads((_EXAMPLES_DIR / fname).read_text())

    def _sources(self, adapter, gap_days: float | None) -> list[SourceRef]:
        # In DEMO mode (no live GEE/Sentinel Hub credentials configured) these
        # connectors are wired and ready but did NOT actually fire for this
        # snapshot -- only the fixture did. Marking them fired=True here would
        # be exactly the "stitched/fabricated evidence" failure mode this
        # platform exists to eliminate.
        live = settings.is_live_capable()
        sources = [
            SourceRef(source_id="sentinel2", name="Sentinel-2 L2A NDVI/phenology", access_method="sentinelhub_statistics", version="2026-08", fired=live),
            SourceRef(source_id="sentinel1", name="Sentinel-1 GRD VH backscatter", access_method="gee", version="2026-08", fired=live),
            SourceRef(source_id="dynamic_world", name="Dynamic World V1 crop probability", access_method="gee", version="2026-08", fired=live),
            SourceRef(source_id=adapter.rainfall_source(), name=f"{adapter.rainfall_source().upper()} rainfall/weather context", access_method="gee", version="2026-08", fired=live),
        ]
        if adapter.supports_field_level_crop_source():
            sources.append(SourceRef(source_id="amed", name="Google AMED field-level crop prediction", access_method="amed", version="2026-08", fired=settings.amed_enabled))
        sources.append(SourceRef(source_id="demo_fixture", name="Deterministic demo fixture (MVP pilot)", access_method="fixture", version="2026-08-22", fired=True))
        return sources

    def build_sowing(self, *, admin_id: str, crop_id: str, season_id: str, fixture: dict, adapter) -> SowingProgressResponse:
        d = fixture["sowing"]
        r = calculate_sowing_progress(
            d["detected_established_area_ha"], d["target_area_ha"],
            d["expected_progress_pct"], d["weekly_history"],
        )
        stages = stage_distribution(d["stage_established_pct"], d["stage_emerging_pct"], d["stage_uncertain_pct"])

        raw_score = confidence_score(
            temporal_density=d["temporal_density"], sensor_agreement=d["sensor_agreement"],
            classifier_prob=d["classifier_prob"], spatial_support=d["spatial_support"],
            historical_consistency=d["historical_consistency"], model_uncertainty=d["model_uncertainty"],
            field_level_source_agreement=d.get("field_level_source_agreement") if adapter.supports_field_level_crop_source() else None,
        )
        score = penalize_for_staleness(raw_score, d.get("observation_gap_days"))

        observed = datetime.fromisoformat(d["observation_date"].replace("Z", "+00:00"))
        processed = datetime.fromisoformat(d["processed_date"])
        trace = make_trace_id({"module": "sowing", "country_id": adapter.country_id, "admin_id": admin_id, "crop_id": crop_id, "season_id": season_id, "obs": d["observation_date"]})

        return SowingProgressResponse(
            country_id=adapter.country_id, admin_id=admin_id, crop_id=crop_id, season_id=season_id,
            detected_established_area_ha=r.detected_area_ha, target_area_ha=r.target_area_ha,
            remaining_area_ha=r.remaining_area_ha, progress_pct=round(r.progress_pct, 4),
            expected_progress_pct=r.expected_progress_pct,
            deviation=Deviation(value=round(r.deviation_pp, 4), unit="percentage_points", basis="progress_share"),
            weekly_rate_pp=r.weekly_rate_pp, status=r.status, stage_distribution=stages,
            confidence=Confidence(score=round(score, 4), label=ConfidenceClass(confidence_label(score)), components={
                "temporal_density": d["temporal_density"], "sensor_agreement": d["sensor_agreement"],
                "classifier_prob": d["classifier_prob"], "spatial_support": d["spatial_support"],
                "historical_consistency": d["historical_consistency"], "model_uncertainty": d["model_uncertainty"],
                **({"field_level_source_agreement": d["field_level_source_agreement"]} if adapter.supports_field_level_crop_source() else {}),
            }),
            freshness=Freshness(observed_at=observed, processed_at=processed, age_hours=round((processed - observed).total_seconds() / 3600, 2), observation_gap_days=d.get("observation_gap_days")),
            spatial_support=SpatialSupport(total_pixels=d.get("total_pixels"), valid_pixels=d.get("valid_pixels"), coverage_fraction=round(d.get("valid_pixels", 0) / d["total_pixels"], 4) if d.get("total_pixels") else None, mmu_status="ok"),
            lineage=Lineage(computation_trace_id=trace, model_run_id="sowing_rules_v2", feature_snapshot_id=f"{admin_id}-snapshot", geometry_version="unversioned_placeholder", sources=self._sources(adapter, d.get("observation_gap_days"))),
            data_status=DataStatus.DEMO,
        )

    def build_yield(self, *, admin_id: str, crop_id: str, season_id: str, fixture: dict, adapter) -> YieldPerformanceResponse:
        d = fixture["yield"]
        r = calculate_yield_impact(
            area_ha=d["area_ha"], estimated_yield_kg_ha=d["estimated_yield_kg_ha"],
            historical_expected_yield_kg_ha=d["historical_expected_yield_kg_ha"],
            attainable_yield_kg_ha=d["attainable_yield_kg_ha"],
            price_value=d["price_value"], price_unit=d["price_unit"],
        )
        trace = make_trace_id({"module": "yield", "country_id": adapter.country_id, "admin_id": admin_id, "crop_id": crop_id, "season_id": season_id, "area": d["area_ha"]})
        now = now_utc()

        return YieldPerformanceResponse(
            country_id=adapter.country_id, admin_id=admin_id, crop_id=crop_id, season_id=season_id,
            estimated_yield_kg_ha=r.estimated_yield_kg_ha, historical_expected_yield_kg_ha=r.historical_expected_yield_kg_ha,
            attainable_yield_kg_ha=r.attainable_yield_kg_ha, seasonal_anomaly_kg_ha=r.seasonal_anomaly_kg_ha,
            yield_gap_kg_ha=r.yield_gap_kg_ha, relative_yield_gap_pct=r.relative_yield_gap_pct,
            production_gap_mt=r.production_gap_mt, economic_exposure=r.economic_exposure,
            price_basis={"value": d["price_value"], "unit": d["price_unit"], "basis": d["price_basis"], "as_of": d["price_as_of"], "currency": adapter.price_currency(), "granularity_note": adapter.price_granularity_note()},
            counterfactual_tier=d["counterfactual_tier"],
            confidence=Confidence(score=0.66, label=ConfidenceClass.MEDIUM, components={"demo_baseline": 1.0}),
            freshness=Freshness(observed_at=now, processed_at=now, age_hours=0),
            lineage=Lineage(computation_trace_id=trace, model_run_id="yield_benchmark_v1", feature_snapshot_id=f"{admin_id}-yield-snapshot", sources=self._sources(adapter, None)),
            data_status=DataStatus.DEMO,
        )

    def build_situation(self, sowing: SowingProgressResponse, yield_perf: YieldPerformanceResponse, crop_name: str) -> AgriculturalSituation:
        risk = "Low"
        if yield_perf.relative_yield_gap_pct > 25 or sowing.deviation.value < -10:
            risk = "High"
        elif yield_perf.relative_yield_gap_pct > 10 or sowing.deviation.value < -3:
            risk = "Moderate"
        overall = sowing.confidence.label if sowing.confidence.score <= yield_perf.confidence.score else yield_perf.confidence.label
        return AgriculturalSituation(
            headline_crop=crop_name,
            sowing_deviation_pp=sowing.deviation.value,
            crop_condition_sigma=None,
            yield_vs_historical_pct=round((yield_perf.estimated_yield_kg_ha - yield_perf.historical_expected_yield_kg_ha) / yield_perf.historical_expected_yield_kg_ha * 100, 2),
            production_gap_mt=yield_perf.production_gap_mt,
            risk_label=risk,
            overall_confidence_label=overall.value,
            data_status=DataStatus.DEMO,
        )

    def get_snapshot(self, *, admin_id: str, crop_id: str, season_id: str) -> AgriSnapshot:
        geo = self.geography.resolve(admin_id)
        adapter = get_adapter(geo["country_id"])
        fixture = self._load_fixture(admin_id)

        sowing = self.build_sowing(admin_id=admin_id, crop_id=crop_id, season_id=season_id, fixture=fixture, adapter=adapter)
        yield_perf = self.build_yield(admin_id=admin_id, crop_id=crop_id, season_id=season_id, fixture=fixture, adapter=adapter)
        crops_here = [CropsGrownHereEntry(**c) for c in fixture.get("crops_grown_here", [])]
        situation = self.build_situation(sowing, yield_perf, crop_id.capitalize())

        snap_id = make_snapshot_id({"admin_id": admin_id, "crop_id": crop_id, "season_id": season_id, "as_of": sowing.freshness.observed_at.isoformat()})

        return AgriSnapshot(
            snapshot_id=snap_id,
            generated_at=now_utc(),
            identity=Identity(
                country_id=geo["country_id"], admin_id=geo["admin_id"], admin_level=geo["admin_level"],
                canonical_name=geo["canonical_name"], breadcrumb=geo["breadcrumb"],
                crop_id=crop_id, season_id=season_id, analysis_date=date.today(),
                geometry_version="unversioned_placeholder", model_version="snapshot_v1",
            ),
            crops_grown_here=crops_here,
            situation=situation,
            sowing=sowing,
            yield_performance=yield_perf,
            data_status=DataStatus.DEMO,
        )


# ======================================================================
# LIVE path -- real connector fan-out (no fixtures, no invented numbers)
# ======================================================================

logger = logging.getLogger(__name__)

_BOUNDARIES_DIR = Path(__file__).resolve().parents[1] / "static" / "boundaries" / "india_districts"
_GEOJSON_CACHE: dict[str, dict] = {}


class SnapshotSource(str, Enum):
    FIXTURE = "FIXTURE"
    LIVE = "LIVE"


class GeometryNotAvailable(LookupError):
    """Raised when a registered admin unit has no usable boundary polygon.
    Live analytics are impossible without geometry -- we surface this instead
    of silently analysing a bounding box of the wrong place."""


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _state_slug(admin_id: str, parent_admin_id: str | None) -> str:
    """'IND-ADMIN1-MADHYA-PRADESH' -> 'madhya-pradesh' (the geojson filename)."""
    src = parent_admin_id or admin_id
    for prefix in ("IND-ADMIN1-", "IND-ADMIN2-"):
        if src.startswith(prefix):
            src = src[len(prefix):]
            break
    return src.lower()


def _load_state_geojson(slug: str) -> dict:
    if slug not in _GEOJSON_CACHE:
        path = _BOUNDARIES_DIR / f"{slug}.geojson"
        if not path.exists():
            raise GeometryNotAvailable(
                f"No district boundary file '{path.name}' in {_BOUNDARIES_DIR.name}/"
            )
        _GEOJSON_CACHE[slug] = json.loads(path.read_text(encoding="utf-8"))
    return _GEOJSON_CACHE[slug]


def geometry_for(geography: GeographyService, admin_id: str) -> dict:
    """Resolves an admin_id to its GeoJSON geometry dict from the bundled
    district boundaries. India admin2 only for now -- that is the only level
    this repo ships real polygons for (see docs/KNOWN_LIMITATIONS.md)."""
    unit = geography.get_unit(admin_id)
    if unit.get("country_id") != "IND":
        raise GeometryNotAvailable(
            f"{admin_id}: bundled boundaries currently cover India districts only"
        )
    if unit.get("admin_level") != 2:
        raise GeometryNotAvailable(
            f"{admin_id} is admin_level {unit.get('admin_level')}; live analytics "
            f"need district (level 2) geometry"
        )

    slug = _state_slug(admin_id, unit.get("parent_admin_id"))
    collection = _load_state_geojson(slug)
    target = _norm(unit["canonical_name"])
    for feature in collection.get("features", []):
        props = feature.get("properties") or {}
        if _norm(props.get("NAME_2", "")) == target:
            geom = feature.get("geometry")
            if not geom:
                break
            return geom
    raise GeometryNotAvailable(
        f"District '{unit['canonical_name']}' not found as NAME_2 in {slug}.geojson"
    )


# ---- geometry math (no geo deps: equirectangular scaling + shoelace) ----

def _flatten_coordinates(coords):
    if isinstance(coords, (list, tuple)):
        if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
            yield (float(coords[0]), float(coords[1]))
        else:
            for c in coords:
                yield from _flatten_coordinates(c)


def _geometry_to_bbox(geometry: dict) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    for lon, lat in _flatten_coordinates(geometry.get("coordinates")):
        xs.append(lon)
        ys.append(lat)
    if not xs:
        raise GeometryNotAvailable("geometry contains no coordinates")
    return [min(xs), min(ys), max(xs), max(ys)]


def _geometry_centroid(geometry: dict) -> tuple[float, float]:
    x1, y1, x2, y2 = _geometry_to_bbox(geometry)
    return ((y1 + y2) / 2.0, (x1 + x2) / 2.0)  # (lat, lng)


def _ring_area_ha(ring: list) -> float:
    if not ring or len(ring) < 3:
        return 0.0
    lats = [p[1] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not lats:
        return 0.0
    kx = 111.320 * math.cos(math.radians(sum(lats) / len(lats)))  # km per deg lon
    ky = 110.574                                                  # km per deg lat
    n = len(ring)
    acc = 0.0
    for i in range(n):
        p, q = ring[i], ring[(i + 1) % n]
        acc += (p[0] * kx) * (q[1] * ky) - (q[0] * kx) * (p[1] * ky)
    return abs(acc) / 2.0 * 100.0  # km^2 -> ha


def _estimate_admin_area_ha(geometry: dict) -> float:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        polygons = [coords]
    elif gtype == "MultiPolygon":
        polygons = coords
    else:
        return 0.0
    total = 0.0
    for poly in polygons:
        if not poly:
            continue
        total += _ring_area_ha(poly[0])
        for hole in poly[1:]:
            total -= _ring_area_ha(hole)
    return max(0.0, round(total, 1))


# ---- connector response extractors -------------------------------------

def _extract_ndvi_series(stats: dict, expected_intervals: int) -> dict | None:
    """Parses a Sentinel Hub Statistics API response into the aggregate facts
    the confidence model needs. Returns None when no interval carried valid
    pixels -- an empty response must never become a number."""
    means: list[float] = []
    coverages: list[float] = []
    latest_from: str | None = None

    for interval in stats.get("data") or []:
        bands = ((interval.get("outputs") or {}).get("ndvi") or {}).get("bands") or {}
        band = bands.get("B0") or (next(iter(bands.values())) if bands else {})
        st = band.get("stats") or {}
        mean = st.get("mean")
        sample = st.get("sampleCount") or 0
        nodata = st.get("noDataCount") or 0
        if mean is None or sample <= 0:
            continue
        valid = sample - nodata
        if valid <= 0:
            continue
        means.append(float(mean))
        coverages.append(valid / sample)
        latest_from = (interval.get("interval") or {}).get("from") or latest_from

    if not means:
        return None

    recent = means[-3:]
    return {
        "mean": round(sum(recent) / len(recent), 4),
        "valid_intervals": len(means),
        "coverage": round(sum(coverages) / len(coverages), 4),
        "temporal_density": round(min(1.0, len(means) / max(1, expected_intervals)), 4),
        "latest_from": latest_from,
    }


def _first_number(payload: dict | None, *keys: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        val = payload.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _multi_sensor_agreement(values: list[float | None]) -> float:
    """Agreement across independent crop-signal sources. With one source we
    cannot claim corroboration, so the score stays deliberately low."""
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return 0.4 if present else 0.0
    spread = max(present) - min(present)
    return round(max(0.0, min(1.0, 1.0 - spread)), 4)


class LiveSnapshotBuilder:
    """Builds an AgriSnapshot from REAL connector output only.

    Every connector is probed independently and a failure is isolated: it is
    recorded as fired=False in lineage and drops out of the confidence model,
    rather than failing the whole snapshot or being back-filled with a demo
    value. If nothing fires, the snapshot comes back data_status=UNAVAILABLE
    with sowing=None -- the renderer then simply shows no cards, which is the
    honest outcome.

    Deliberately NOT produced here: yield_performance. A yield gap needs
    attainable + historical-expected baselines, which require the historical
    baseline table in docs/PRODUCTION_IMPLEMENTATION_PLAN.md §4. Inventing
    those two numbers is exactly the failure mode this platform forbids, so
    live snapshots omit the yield block until that pipeline exists.
    """

    NDVI_WINDOW_DAYS = 40
    AGG_DAYS = 5

    def __init__(self, geography: GeographyService | None = None, catalog=None):
        self.geography = geography or GeographyService()

        # Imported lazily so importing this module never depends on optional
        # live extras (earthengine-api) being installed.
        from .catalog import CatalogService
        from .connectors.earth_engine import EarthEngineConnector
        from .connectors.sentinelhub import SentinelHubStatisticsClient
        from .connectors.weather import WeatherContextClient
        from .connectors.worldcereal import WorldCerealClient
        from .connectors.amed import AmedClient

        self.catalog = catalog or CatalogService()
        self.ee = EarthEngineConnector(settings.gee_project, settings.gee_service_account_json_path)
        self.sentinelhub = SentinelHubStatisticsClient(
            settings.sentinelhub_base_url,
            settings.sentinelhub_client_id,
            settings.sentinelhub_client_secret,
            settings.sentinelhub_token_url,
        )
        self.weather = WeatherContextClient(self.ee)
        self.worldcereal = WorldCerealClient(self.ee)
        self.amed = AmedClient(settings.amed_api_key, settings.amed_enabled)

    # ---- season calendar ------------------------------------------------
    def _expected_progress_pct(self, country_id: str, crop_id: str, season_id: str, today: date) -> float | None:
        """Share of the sowing window elapsed, from the seed season calendar.
        Returns None when this season isn't in the calendar -- the caller then
        reports progress without claiming a deviation it cannot justify."""
        for season in self.catalog.seasons_for(country_id, crop_id):
            if season.get("season_id") != season_id:
                continue
            try:
                start = date.fromisoformat(str(season["sowing_start"]))
                end = date.fromisoformat(str(season["sowing_end"]))
            except (KeyError, ValueError):
                return None
            span = (end - start).days
            if span <= 0:
                return None
            return round(max(0.0, min(1.0, (today - start).days / span)) * 100, 2)
        return None

    # ---- the build ------------------------------------------------------
    def build(self, *, admin_id: str, crop_id: str, season_id: str) -> AgriSnapshot:
        geo = self.geography.resolve(admin_id)
        adapter = get_adapter(geo["country_id"])
        geometry = geometry_for(self.geography, geo["admin_id"])

        bbox = _geometry_to_bbox(geometry)
        lat, lng = _geometry_centroid(geometry)
        area_ha = _estimate_admin_area_ha(geometry)

        today = date.today()
        win_from = (today - timedelta(days=self.NDVI_WINDOW_DAYS)).isoformat()
        win_to = today.isoformat()
        expected_intervals = max(1, self.NDVI_WINDOW_DAYS // self.AGG_DAYS)

        fired: dict[str, bool] = {}

        def probe(name: str, fn):
            """Runs one connector with total failure isolation."""
            try:
                value = fn()
            except Exception as exc:  # noqa: BLE001 - deliberate: isolate every connector
                logger.warning("live connector %s failed for %s: %s: %s",
                               name, admin_id, type(exc).__name__, exc)
                fired[name] = False
                return None
            fired[name] = value is not None
            return value

        # --- Sentinel-2 NDVI via Sentinel Hub Statistics API (primary) ----
        def _sh_ndvi():
            if not self.sentinelhub.configured():
                return None
            payload = self.sentinelhub.ndvi_timeseries_payload(bbox, win_from, win_to)
            raw = asyncio.run(self.sentinelhub.statistics(payload))
            return _extract_ndvi_series(raw, expected_intervals)

        ndvi_series = probe("sentinel2", _sh_ndvi)

        # --- Sentinel-2 NDVI via GEE (fallback if Sentinel Hub gave nothing)
        if ndvi_series is None:
            def _gee_ndvi():
                if not self.ee.configured():
                    return None
                raw = self.ee.ndvi_stats_for_geometry(geometry, win_from, win_to)
                mean = _first_number(raw, "NDVI_mean", "NDVI", "nd_mean", "nd")
                if mean is None:
                    return None
                return {"mean": round(mean, 4), "valid_intervals": 1,
                        "coverage": 1.0, "temporal_density": 0.3, "latest_from": None}
            ndvi_series = probe("sentinel2", _gee_ndvi)

        # --- Dynamic World crop probability ------------------------------
        def numeric_probe(name: str, call, *keys: str):
            """GEE reducer -> single number, logging the RAW payload when the
            expected key is absent. A silent None here used to zero out
            target_area_ha and blank the entire snapshot with no explanation."""
            def _run():
                if not self.ee.configured():
                    return None
                raw = call()
                value = _first_number(raw, *keys)
                if value is None:
                    logger.warning(
                        "live connector %s returned no usable number for %s "
                        "(wanted one of %s); raw=%r", name, admin_id, keys, raw,
                    )
                return value
            return probe(name, _run)

        dw_prob = numeric_probe(
            "dynamic_world",
            lambda: self.ee.dynamic_world_crop_probability(geometry, win_from, win_to),
            "crops",
        )

        # --- Sentinel-1 VH backscatter (cloud-independent corroboration) --
        s1_vh = numeric_probe(
            "sentinel1",
            lambda: self.ee.sentinel1_vh_backscatter_stats(geometry, win_from, win_to),
            "VH_mean", "VH",
        )

        # --- Rainfall context --------------------------------------------
        rain_mm = numeric_probe(
            adapter.rainfall_source(),
            lambda: self.weather.rainfall_mm(geometry, win_from, win_to),
            "precipitation",
        )

        # --- WorldCereal cropland fraction -------------------------------
        wc_pct = numeric_probe(
            "worldcereal",
            lambda: self.worldcereal.crop_extent(geometry),
            "classification", "temporarycrops",
        )
        # 'classification' is a 0/100 mask, so its regional mean is a
        # percentage -- normalise to the 0-1 fraction the model expects.
        wc_frac = None if wc_pct is None else round(max(0.0, min(1.0, wc_pct / 100.0)), 4)

        # --- AMED field-level crop prediction (India only, opt-in) --------
        amed_payload = None
        if adapter.supports_field_level_crop_source():
            amed_payload = probe("amed", lambda: (
                asyncio.run(self.amed.field_crop_predictions(
                    country_id=geo["country_id"], lat=lat, lng=lng))
                if self.amed.configured() else None))

        # --- assemble ----------------------------------------------------
        ndvi = ndvi_series["mean"] if ndvi_series else None
        # WorldCereal is a fraction 0-1; Dynamic World 'crops' is a probability
        # 0-1. Either can carry cropland extent; prefer the dedicated product.
        crop_frac = wc_frac if wc_frac is not None else dw_prob
        target_area_ha = round(area_ha * crop_frac, 1) if (area_ha > 0 and crop_frac) else 0.0

        sources = self._live_sources(adapter, fired)
        sowing = None
        if ndvi is not None and target_area_ha > 0:
            sowing = self._build_live_sowing(
                admin_id=geo["admin_id"], crop_id=crop_id, season_id=season_id,
                adapter=adapter, geo=geo, today=today,
                ndvi_series=ndvi_series, target_area_ha=target_area_ha,
                crop_frac=crop_frac, dw_prob=dw_prob, wc_frac=wc_frac,
                s1_vh=s1_vh, rain_mm=rain_mm, amed_payload=amed_payload,
                sources=sources, sentinel2_fired=fired.get("sentinel2", False),
            )
        else:
            logger.warning(
                "live snapshot for %s produced no sowing block (ndvi=%s, target_area_ha=%s, "
                "fired=%s)", admin_id, ndvi, target_area_ha, fired,
            )

        situation = None
        if sowing is not None:
            dev = sowing.deviation.value
            risk = "High" if dev < -10 else "Moderate" if dev < -3 else "Low"
            situation = AgriculturalSituation(
                headline_crop=crop_id.capitalize(),
                sowing_deviation_pp=dev,
                crop_condition_sigma=None,
                # Needs the historical baseline table (plan §4) -- not invented.
                yield_vs_historical_pct=None,
                production_gap_mt=None,
                risk_label=risk,
                overall_confidence_label=sowing.confidence.label.value,
                data_status=sowing.data_status,
            )

        overall_status = sowing.data_status if sowing else DataStatus.UNAVAILABLE
        snap_id = make_snapshot_id({
            "admin_id": geo["admin_id"], "crop_id": crop_id, "season_id": season_id,
            "as_of": today.isoformat(), "mode": "live",
        })

        return AgriSnapshot(
            snapshot_id=snap_id,
            generated_at=now_utc(),
            identity=Identity(
                country_id=geo["country_id"], admin_id=geo["admin_id"],
                admin_level=geo["admin_level"], canonical_name=geo["canonical_name"],
                breadcrumb=geo["breadcrumb"], crop_id=crop_id, season_id=season_id,
                analysis_date=today,
                geometry_version="bundled_district_geojson_2026-08-23",
                model_version="snapshot_live_v1",
            ),
            # Cropland extent tells us how much is cropped, not WHICH crop --
            # so no crop-share breakdown is claimed from it.
            crops_grown_here=[],
            situation=situation,
            sowing=sowing,
            yield_performance=None,
            data_status=overall_status,
        )

    # ---- helpers --------------------------------------------------------
    def _live_sources(self, adapter, fired: dict[str, bool]) -> list[SourceRef]:
        sources = [
            SourceRef(source_id="sentinel2", name="Sentinel-2 L2A NDVI/phenology",
                      access_method="sentinelhub_statistics", version="2026-08",
                      fired=fired.get("sentinel2", False)),
            SourceRef(source_id="sentinel1", name="Sentinel-1 GRD VH backscatter",
                      access_method="gee", version="2026-08",
                      fired=fired.get("sentinel1", False)),
            SourceRef(source_id="dynamic_world", name="Dynamic World V1 crop probability",
                      access_method="gee", version="2026-08",
                      fired=fired.get("dynamic_world", False)),
            SourceRef(source_id="worldcereal", name="ESA WorldCereal 2021 temporary crops",
                      access_method="gee", version="2021-v100",
                      fired=fired.get("worldcereal", False)),
            SourceRef(source_id=adapter.rainfall_source(),
                      name=f"{adapter.rainfall_source().upper()} rainfall context",
                      access_method="gee", version="2026-08",
                      fired=fired.get(adapter.rainfall_source(), False)),
        ]
        if adapter.supports_field_level_crop_source():
            sources.append(SourceRef(
                source_id="amed", name="Google AMED field-level crop prediction",
                access_method="amed", version="2026-08", fired=fired.get("amed", False)))
        return sources

    def _build_live_sowing(self, *, admin_id, crop_id, season_id, adapter, geo, today,
                           ndvi_series, target_area_ha, crop_frac, dw_prob, wc_frac,
                           s1_vh, rain_mm, amed_payload, sources,
                           sentinel2_fired) -> SowingProgressResponse:
        ndvi = ndvi_series["mean"]
        coverage = ndvi_series.get("coverage") or 0.0

        # NDVI -> establishment share. Below 0.15 is bare soil, at/above 0.45 a
        # closed canopy; in between we scale linearly. This is a documented
        # PROXY, which is why the block is never labelled OBSERVED on its own.
        established_frac = min(1.0, max(0.0, (ndvi - 0.15) / 0.30))
        detected = min(target_area_ha, round(target_area_ha * established_frac, 1))

        expected = self._expected_progress_pct(geo["country_id"], crop_id, season_id, today)
        progress_pct = detected / target_area_ha * 100 if target_area_ha else 0.0
        basis = "sowing_window_elapsed_share"
        if expected is None:
            # No calendar entry -> report progress with no deviation claim.
            expected = round(progress_pct, 4)
            basis = "calendar_unavailable_no_deviation_claimed"

        result = calculate_sowing_progress(detected, target_area_ha, expected, None)
        stages = stage_distribution(
            established_frac * 100.0,
            0.0,                                   # no per-pixel emerging class live yet
            max(0.0, (1.0 - coverage) * 100.0),    # unobserved area is uncertain, not zero
        )

        agreement = _multi_sensor_agreement([
            dw_prob,
            wc_frac,
            # Map VH backscatter (~-25..-5 dB) into 0-1 so it can be compared.
            None if s1_vh is None else max(0.0, min(1.0, (s1_vh + 25.0) / 20.0)),
        ])
        classifier_prob = dw_prob if dw_prob is not None else (crop_frac or 0.0)
        field_agreement = None
        if adapter.supports_field_level_crop_source() and amed_payload is not None:
            field_agreement = 0.8

        raw_score = confidence_score(
            temporal_density=ndvi_series.get("temporal_density") or 0.0,
            sensor_agreement=agreement,
            classifier_prob=max(0.0, min(1.0, classifier_prob)),
            spatial_support=max(0.0, min(1.0, coverage)),
            # Neutral prior on purpose: the historical baseline table (plan §4)
            # does not exist yet, so we neither reward nor punish consistency.
            historical_consistency=0.5,
            model_uncertainty=max(0.0, min(1.0, 1.0 - agreement)),
            field_level_source_agreement=field_agreement,
        )

        latest = ndvi_series.get("latest_from")
        observed_at = now_utc()
        gap_days = None
        if latest:
            try:
                observed_at = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
                gap_days = round((now_utc() - observed_at).total_seconds() / 86400, 2)
            except ValueError:
                observed_at = now_utc()
        score = penalize_for_staleness(raw_score, gap_days)

        processed_at = now_utc()
        trace = make_trace_id({
            "module": "sowing_live", "country_id": geo["country_id"], "admin_id": admin_id,
            "crop_id": crop_id, "season_id": season_id, "ndvi": ndvi,
            "target_area_ha": target_area_ha,
        })

        components = {
            "temporal_density": round(ndvi_series.get("temporal_density") or 0.0, 4),
            "sensor_agreement": agreement,
            "classifier_prob": round(max(0.0, min(1.0, classifier_prob)), 4),
            "spatial_support": round(max(0.0, min(1.0, coverage)), 4),
            "historical_consistency": 0.5,
            "model_uncertainty": round(max(0.0, min(1.0, 1.0 - agreement)), 4),
            "observed_ndvi_mean": ndvi,
        }
        if rain_mm is not None:
            components["rainfall_mm_window"] = round(rain_mm, 2)
        if field_agreement is not None:
            components["field_level_source_agreement"] = field_agreement

        return SowingProgressResponse(
            country_id=geo["country_id"], admin_id=admin_id, crop_id=crop_id,
            season_id=season_id,
            detected_established_area_ha=result.detected_area_ha,
            target_area_ha=result.target_area_ha,
            remaining_area_ha=result.remaining_area_ha,
            progress_pct=round(result.progress_pct, 4),
            expected_progress_pct=result.expected_progress_pct,
            deviation=Deviation(value=round(result.deviation_pp, 4),
                                unit="percentage_points", basis=basis),
            weekly_rate_pp=0.0,   # no live weekly history series yet
            status=result.status,
            stage_distribution=stages,
            confidence=Confidence(score=round(score, 4),
                                  label=ConfidenceClass(confidence_label(score)),
                                  components=components),
            freshness=Freshness(
                observed_at=observed_at, processed_at=processed_at,
                age_hours=round(max(0.0, (processed_at - observed_at).total_seconds() / 3600), 2),
                latest_direct_observation_at=observed_at if latest else None,
                observation_gap_days=gap_days,
            ),
            spatial_support=SpatialSupport(coverage_fraction=round(coverage, 4), mmu_status="ok"),
            lineage=Lineage(
                computation_trace_id=trace, model_run_id="sowing_live_v1",
                feature_snapshot_id=f"{admin_id}-live-snapshot",
                geometry_version="bundled_district_geojson_2026-08-23", sources=sources,
            ),
            # Real satellite reflectance behind it -> OBSERVED; radar/LULC only
            # -> PROXY. Never DEMO on this path.
            data_status=DataStatus.OBSERVED if sentinel2_fired else DataStatus.PROXY,
        )


class SnapshotOrchestrator:
    """Decides whether a request is served from the DEMO fixture path or the
    LIVE connector path, so routes.py and the Celery worker cannot drift apart.

    Routing:
      registered + has a demo fixture  -> FIXTURE (data_status DEMO)
      registered + live-capable        -> LIVE (real fetch)
      registered + NOT live-capable    -> NoFixtureAvailable  (HTTP 501)
      unknown admin_id                 -> UnknownAdminUnit    (HTTP 404)
    """

    def __init__(self, geography: GeographyService | None = None):
        self.geography = geography or GeographyService()
        self.fixtures = SnapshotService(self.geography)
        self._live: LiveSnapshotBuilder | None = None

    @property
    def live(self) -> LiveSnapshotBuilder:
        if self._live is None:
            self._live = LiveSnapshotBuilder(self.geography)
        return self._live

    def resolve_source(self, admin_id: str) -> SnapshotSource:
        geo = self.geography.resolve(admin_id)   # raises UnknownAdminUnit -> 404
        if geo["admin_id"] in _FIXTURE_FILES:
            return SnapshotSource.FIXTURE
        if settings.is_live_capable():
            return SnapshotSource.LIVE
        raise NoFixtureAvailable(
            f"{geo['canonical_name']} ({geo['admin_id']}) has no demo fixture, and no "
            f"live credentials are configured. Set SENTINELHUB_CLIENT_ID + "
            f"SENTINELHUB_CLIENT_SECRET and/or GEE_PROJECT in .env to enable the live "
            f"path (see docs/KNOWN_LIMITATIONS.md)."
        )

    def get_snapshot(self, *, admin_id: str, crop_id: str, season_id: str) -> AgriSnapshot:
        source = self.resolve_source(admin_id)
        if source is SnapshotSource.FIXTURE:
            return self.fixtures.get_snapshot(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
        return self.live.build(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
