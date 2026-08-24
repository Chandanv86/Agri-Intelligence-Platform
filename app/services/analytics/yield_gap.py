from dataclasses import dataclass


@dataclass(frozen=True)
class YieldImpactResult:
    estimated_yield_kg_ha: float
    historical_expected_yield_kg_ha: float
    attainable_yield_kg_ha: float
    seasonal_anomaly_kg_ha: float
    yield_gap_kg_ha: float
    relative_yield_gap_pct: float
    production_gap_mt: float
    economic_exposure: float | None


_PRICE_UNIT_TO_PER_TONNE = {
    # multiplier converting the given price_unit into currency-per-tonne
    "INR_per_quintal": 10,
    "INR_per_kg": 1000,
    "INR_per_tonne": 1,
    "KES_per_kg": 1000,
    "KES_per_tonne": 1,
    "UGX_per_kg": 1000,
    "UGX_per_tonne": 1,
    "TZS_per_kg": 1000,
    "TZS_per_tonne": 1,
    "ETB_per_kg": 1000,
    "ETB_per_tonne": 1,
    "ZAR_per_tonne": 1,
    "ZAR_per_kg": 1000,
}


def calculate_yield_impact(
    *,
    area_ha: float,
    estimated_yield_kg_ha: float,
    historical_expected_yield_kg_ha: float,
    attainable_yield_kg_ha: float,
    price_value: float | None = None,
    price_unit: str | None = None,
) -> YieldImpactResult:
    vals = (area_ha, estimated_yield_kg_ha, historical_expected_yield_kg_ha, attainable_yield_kg_ha)
    if any(v < 0 for v in vals):
        raise ValueError("area/yield values must be >= 0")
    if attainable_yield_kg_ha <= 0:
        raise ValueError("attainable_yield_kg_ha must be > 0")

    gap = max(0.0, attainable_yield_kg_ha - estimated_yield_kg_ha)
    production = area_ha * gap / 1000.0

    exposure = None
    if price_value is not None:
        if price_unit not in _PRICE_UNIT_TO_PER_TONNE:
            raise ValueError(f"unsupported price unit: {price_unit}")
        exposure = production * _PRICE_UNIT_TO_PER_TONNE[price_unit] * price_value

    return YieldImpactResult(
        estimated_yield_kg_ha,
        historical_expected_yield_kg_ha,
        attainable_yield_kg_ha,
        estimated_yield_kg_ha - historical_expected_yield_kg_ha,
        gap,
        gap / attainable_yield_kg_ha * 100,
        production,
        exposure,
    )


def economic_exposure_range(
    production_gap_low_mt: float,
    production_gap_high_mt: float,
    price_low: float,
    price_high: float,
) -> tuple[float, float]:
    """Card 8/53: economic output as a range, not a false-precision point value."""
    low = production_gap_low_mt * price_low
    high = production_gap_high_mt * price_high
    return (round(min(low, high), 2), round(max(low, high), 2))
