from datetime import date, datetime
from pydantic import BaseModel
from .common import DataStatus
from .agriculture import SowingProgressResponse, YieldPerformanceResponse, CropsGrownHereEntry


class Identity(BaseModel):
    country_id: str
    admin_id: str
    admin_level: int
    canonical_name: str
    breadcrumb: list[str]
    crop_id: str | None
    season_id: str | None
    analysis_date: date
    geometry_version: str
    model_version: str


class AgriculturalSituation(BaseModel):
    """The Tier-1 'ten second answer' cross-theme summary card."""
    headline_crop: str
    sowing_deviation_pp: float | None
    crop_condition_sigma: float | None
    yield_vs_historical_pct: float | None
    production_gap_mt: float | None
    risk_label: str
    overall_confidence_label: str
    data_status: DataStatus


class AgriSnapshot(BaseModel):
    """The single unified analytical object every card renders from.
    No card independently calls a second endpoint — this is the platform's
    core architectural rule (docs/ARCHITECTURE.md §3)."""
    snapshot_id: str
    generated_at: datetime
    identity: Identity
    crops_grown_here: list[CropsGrownHereEntry] = []
    situation: AgriculturalSituation | None = None
    sowing: SowingProgressResponse | None = None
    yield_performance: YieldPerformanceResponse | None = None
    data_status: DataStatus
