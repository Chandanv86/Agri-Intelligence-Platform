from dataclasses import dataclass


@dataclass(frozen=True)
class SowingResult:
    detected_area_ha: float
    target_area_ha: float
    remaining_area_ha: float
    progress_pct: float
    expected_progress_pct: float
    deviation_pp: float
    weekly_rate_pp: float
    status: str


def calculate_sowing_progress(
    detected_area_ha: float,
    target_area_ha: float,
    expected_progress_pct: float,
    weekly_history: list[dict] | None = None,
) -> SowingResult:
    if target_area_ha <= 0:
        raise ValueError("target_area_ha must be > 0")
    if detected_area_ha < 0:
        raise ValueError("detected_area_ha must be >= 0")
    if detected_area_ha > target_area_ha + 1e-9:
        raise ValueError("detected_area_ha cannot exceed target_area_ha")

    progress = detected_area_ha / target_area_ha * 100
    remaining = target_area_ha - detected_area_ha
    deviation = progress - expected_progress_pct

    weekly = 0.0
    if weekly_history and len(weekly_history) >= 2:
        weekly = weekly_history[-1]["observed_pct"] - weekly_history[-2]["observed_pct"]

    if deviation >= 3:
        status = "ahead"
    elif deviation > -3:
        status = "on_track"
    elif deviation > -10:
        status = "moderately_delayed"
    else:
        status = "severely_delayed"

    return SowingResult(
        detected_area_ha, target_area_ha, remaining, progress,
        expected_progress_pct, deviation, weekly, status,
    )


def stage_distribution(established_pct: float, emerging_pct: float, uncertain_pct: float) -> dict[str, float]:
    """Card 4 (Crop Stage Distribution): a single 'X% established' number hides
    the emerging/uncertain buckets. Never let established+emerging+uncertain
    silently overshoot 100 -- not_detected absorbs the remainder."""
    established_pct = max(0.0, min(100.0, established_pct))
    emerging_pct = max(0.0, min(100.0 - established_pct, emerging_pct))
    uncertain_pct = max(0.0, min(100.0 - established_pct - emerging_pct, uncertain_pct))
    not_detected_pct = round(100.0 - established_pct - emerging_pct - uncertain_pct, 4)
    return {
        "established": round(established_pct, 4),
        "emerging": round(emerging_pct, 4),
        "not_detected": not_detected_pct,
        "uncertain": round(uncertain_pct, 4),
    }


def catch_up_days(gap_area_ha: float, current_rate_ha_per_day: float) -> float | None:
    """Sowing Card 6. Returns None (not zero, not infinity) when the current
    rate cannot support a meaningful estimate -- an unbounded number here is
    worse than admitting the estimate isn't available."""
    if current_rate_ha_per_day <= 0:
        return None
    if gap_area_ha <= 0:
        return 0.0
    return round(gap_area_ha / current_rate_ha_per_day, 2)
