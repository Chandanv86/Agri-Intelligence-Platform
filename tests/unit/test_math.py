import pytest
from app.services.analytics.sowing import calculate_sowing_progress, stage_distribution, catch_up_days
from app.services.analytics.yield_gap import calculate_yield_impact, economic_exposure_range
from app.services.analytics.confidence import confidence_score, confidence_label, penalize_for_staleness


def test_sowing_progress_basic():
    r = calculate_sowing_progress(50, 200, 30)
    assert r.progress_pct == 25
    assert r.remaining_area_ha == 150
    assert r.deviation_pp == pytest.approx(-5)
    assert r.status == "moderately_delayed"


def test_sowing_progress_rejects_overshoot():
    with pytest.raises(ValueError):
        calculate_sowing_progress(300, 200, 30)


def test_sowing_progress_rejects_zero_target():
    with pytest.raises(ValueError):
        calculate_sowing_progress(10, 0, 30)


def test_sowing_status_bands():
    assert calculate_sowing_progress(35, 100, 30).status == "ahead"       # +5pp
    assert calculate_sowing_progress(31, 100, 30).status == "on_track"    # +1pp
    assert calculate_sowing_progress(25, 100, 30).status == "moderately_delayed"  # -5pp
    assert calculate_sowing_progress(15, 100, 30).status == "severely_delayed"    # -15pp


def test_stage_distribution_sums_to_100():
    d = stage_distribution(70.4, 6.0, 3.0)
    assert d["established"] == 70.4
    assert round(sum(d.values()), 4) == 100.0
    assert d["not_detected"] == pytest.approx(20.6)


def test_stage_distribution_clamps_overshoot():
    d = stage_distribution(120, 50, 50)
    assert round(sum(d.values()), 4) == 100.0


def test_catch_up_days_none_when_rate_nonpositive():
    assert catch_up_days(1000, 0) is None
    assert catch_up_days(1000, -5) is None


def test_catch_up_days_zero_gap():
    assert catch_up_days(0, 500) == 0.0


def test_yield_impact_basic():
    r = calculate_yield_impact(
        area_ha=1000, estimated_yield_kg_ha=3000,
        historical_expected_yield_kg_ha=3200, attainable_yield_kg_ha=4000,
    )
    assert r.yield_gap_kg_ha == 1000
    assert r.production_gap_mt == 1000  # 1000 ha * 1000 kg/ha / 1000
    assert r.seasonal_anomaly_kg_ha == -200
    assert r.relative_yield_gap_pct == pytest.approx(25.0)


def test_yield_impact_gap_never_negative():
    r = calculate_yield_impact(
        area_ha=1000, estimated_yield_kg_ha=5000,
        historical_expected_yield_kg_ha=3200, attainable_yield_kg_ha=4000,
    )
    assert r.yield_gap_kg_ha == 0
    assert r.production_gap_mt == 0


def test_yield_impact_rejects_nonpositive_attainable():
    with pytest.raises(ValueError):
        calculate_yield_impact(area_ha=1000, estimated_yield_kg_ha=3000,
                                historical_expected_yield_kg_ha=3200, attainable_yield_kg_ha=0)


def test_yield_impact_multi_currency_price_units():
    r = calculate_yield_impact(
        area_ha=1000, estimated_yield_kg_ha=3000, historical_expected_yield_kg_ha=3200,
        attainable_yield_kg_ha=4000, price_value=50, price_unit="KES_per_kg",
    )
    # production_gap_mt = 1000t -> * 1000 (kg per tonne conversion factor) * 50 = 50,000,000
    assert r.economic_exposure == 50_000_000


def test_yield_impact_rejects_unknown_price_unit():
    with pytest.raises(ValueError):
        calculate_yield_impact(area_ha=1000, estimated_yield_kg_ha=3000,
                                historical_expected_yield_kg_ha=3200, attainable_yield_kg_ha=4000,
                                price_value=10, price_unit="GBP_per_stone")


def test_economic_exposure_range_is_ordered():
    low, high = economic_exposure_range(0.31, 0.56, 2050, 2550)
    assert low <= high


def test_confidence_score_bounds():
    s = confidence_score(temporal_density=1, sensor_agreement=1, classifier_prob=1,
                          spatial_support=1, historical_consistency=1, model_uncertainty=0)
    assert s == pytest.approx(1.0)
    s0 = confidence_score(temporal_density=0, sensor_agreement=0, classifier_prob=0,
                           spatial_support=0, historical_consistency=0, model_uncertainty=1)
    assert s0 == pytest.approx(0.0)


def test_confidence_score_amed_component_changes_weighting():
    without = confidence_score(temporal_density=0.8, sensor_agreement=0.8, classifier_prob=0.8,
                                spatial_support=0.8, historical_consistency=0.8, model_uncertainty=0.2)
    with_amed_high = confidence_score(temporal_density=0.8, sensor_agreement=0.8, classifier_prob=0.8,
                                       spatial_support=0.8, historical_consistency=0.8, model_uncertainty=0.2,
                                       field_level_source_agreement=1.0)
    assert with_amed_high > without


def test_confidence_label_bands():
    assert confidence_label(0.9) == "high"
    assert confidence_label(0.7) == "medium"
    assert confidence_label(0.3) == "low"


def test_staleness_penalty_increases_with_gap():
    base = 0.9
    assert penalize_for_staleness(base, 2) == base
    assert penalize_for_staleness(base, 8) < base
    assert penalize_for_staleness(base, 25) < penalize_for_staleness(base, 8)


def test_staleness_penalty_none_gap_is_noop():
    assert penalize_for_staleness(0.75, None) == 0.75
