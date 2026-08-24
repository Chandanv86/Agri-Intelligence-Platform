from datetime import date
from pydantic import BaseModel, Field
from .common import Confidence, DataStatus, Deviation, Freshness, Lineage, UncertaintyRange, SpatialSupport


class Crop(BaseModel):
    crop_id: str
    canonical_name: str
    duration_class: str | None = None
    ecotype: str | None = None
    local_names: dict[str, list[str]] = Field(default_factory=dict)


class SeasonWindow(BaseModel):
    """One cropping window. Countries with multiple concurrent/overlapping
    rain-fed seasons (Ethiopia Belg/Meher, Kenya/Tanzania long/short rains,
    Uganda's two maize seasons) return MORE THAN ONE of these per crop per
    year — a season is not assumed to be a single annual block."""
    season_id: str
    country_id: str
    crop_id: str
    name: str                      # "Kharif 2026", "Long Rains 2026", "Meher 2026"
    region_scope: list[str] = Field(default_factory=list)  # admin_ids this window applies to; [] = national
    start_date: date
    end_date: date
    sowing_start: date
    sowing_end: date


class CropsGrownHereEntry(BaseModel):
    crop_id: str
    canonical_name: str
    area_share_pct: float
    source: str
    data_status: DataStatus


class SowingProgressResponse(BaseModel):
    country_id: str
    admin_id: str
    crop_id: str
    season_id: str
    detected_established_area_ha: float
    target_area_ha: float
    remaining_area_ha: float
    progress_pct: float
    expected_progress_pct: float
    deviation: Deviation
    weekly_rate_pp: float
    status: str
    stage_distribution: dict[str, float] | None = None   # established/emerging/not_detected/uncertain
    confidence: Confidence
    freshness: Freshness
    spatial_support: SpatialSupport
    lineage: Lineage
    data_status: DataStatus


class YieldPerformanceResponse(BaseModel):
    country_id: str
    admin_id: str
    crop_id: str
    season_id: str
    estimated_yield_kg_ha: float
    historical_expected_yield_kg_ha: float
    attainable_yield_kg_ha: float
    seasonal_anomaly_kg_ha: float
    yield_gap_kg_ha: float
    relative_yield_gap_pct: float
    production_gap_mt: float
    economic_exposure: float | None = None
    economic_exposure_range: UncertaintyRange | None = None
    price_basis: dict | None = None
    counterfactual_tier: str
    yield_interval: UncertaintyRange | None = None
    confidence: Confidence
    freshness: Freshness
    lineage: Lineage
    data_status: DataStatus
