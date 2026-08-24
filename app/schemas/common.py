from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class DataStatus(str, Enum):
    """Every metric in the platform must carry one of these. This is the single
    highest-leverage contract in the system: it is what stops the product from
    silently presenting a demo/fixture number as a real observation."""
    OBSERVED = "OBSERVED"
    MODELLED = "MODELLED"
    ESTIMATED = "ESTIMATED"
    DERIVED = "DERIVED"
    FORECAST = "FORECAST"
    HISTORICAL = "HISTORICAL"
    PROXY = "PROXY"
    SCENARIO = "SCENARIO"
    DEMO = "DEMO"
    UNAVAILABLE = "UNAVAILABLE"


class ConfidenceClass(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(BaseModel):
    score: float = Field(ge=0, le=1)
    label: ConfidenceClass
    components: dict[str, float] = Field(default_factory=dict)
    model_version: str = "confidence_v2"


class Freshness(BaseModel):
    observed_at: datetime
    processed_at: datetime
    age_hours: float
    latest_direct_observation_at: datetime | None = None
    observation_gap_days: float | None = None


class Deviation(BaseModel):
    value: float
    unit: str  # e.g. "percentage_points", "kg_ha", "pct_relative"
    basis: str  # what it's a deviation from, e.g. "expected_progress_curve"


class SourceRef(BaseModel):
    source_id: str
    name: str
    access_method: str  # fixture | gee | sentinelhub_statistics | stac | amed | worldcereal | era5 | chirps
    version: str
    fired: bool = True  # whether this source actually contributed evidence to this snapshot


class Lineage(BaseModel):
    computation_trace_id: str
    model_run_id: str
    feature_snapshot_id: str
    geometry_version: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)


class UncertaintyRange(BaseModel):
    low: float
    mid: float
    high: float
    method: str = "not_specified"  # e.g. quantile_regression, historical_p10_p90, monte_carlo


class SpatialSupport(BaseModel):
    total_pixels: int | None = None
    valid_pixels: int | None = None
    coverage_fraction: float | None = None
    mmu_status: str = "ok"  # ok | aggregated_due_to_mmu | insufficient_observation
