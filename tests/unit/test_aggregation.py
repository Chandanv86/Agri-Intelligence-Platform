import pytest
from app.services.analytics.aggregation import (
    ChildUnit, aggregate_progress, aggregate_yield, spatial_spread, area_share_by_status,
)


def _children():
    return [
        ChildUnit("A", established_area_ha=100, target_area_ha=200, yield_kg_ha=3000, area_ha=200),
        ChildUnit("B", established_area_ha=50, target_area_ha=100, yield_kg_ha=4000, area_ha=100),
    ]


def test_aggregate_progress_is_sum_over_sum_not_mean():
    # child A progress = 50%, child B progress = 50% -> naive mean would also be 50,
    # so use asymmetric example to prove it's not doing per-child averaging.
    children = [
        ChildUnit("A", established_area_ha=10, target_area_ha=100, yield_kg_ha=1, area_ha=100),   # 10%
        ChildUnit("B", established_area_ha=90, target_area_ha=100, yield_kg_ha=1, area_ha=100),    # 90%
    ]
    # mean(child progress) would be 50%; sum/sum must also be 50% here by symmetry of areas.
    assert aggregate_progress(children) == 50.0

    children2 = [
        ChildUnit("A", established_area_ha=10, target_area_ha=100, yield_kg_ha=1, area_ha=100),    # 10%, weight 100
        ChildUnit("B", established_area_ha=900, target_area_ha=1000, yield_kg_ha=1, area_ha=1000),  # 90%, weight 1000
    ]
    # mean(child progress) = 50%, but sum/sum = 910/1100 = 82.7% -- proves this is NOT mean-of-children
    result = aggregate_progress(children2)
    assert result != 50.0
    assert result == pytest.approx(82.7273, rel=1e-3)


def test_aggregate_yield_is_area_weighted():
    children = _children()
    # naive mean(3000,4000)=3500; area-weighted = (3000*200+4000*100)/300 = 3333.33
    result = aggregate_yield(children)
    assert result != 3500
    assert result == pytest.approx(3333.3333, rel=1e-3)


def test_aggregate_progress_rejects_zero_target():
    with pytest.raises(ValueError):
        aggregate_progress([ChildUnit("A", 0, 0, 0, 0)])


def test_spatial_spread_p10_p90():
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    result = spatial_spread(values)
    assert result["p10"] < result["p90"]
    assert result["spread"] == pytest.approx(result["p90"] - result["p10"])


def test_spatial_spread_rejects_empty():
    with pytest.raises(ValueError):
        spatial_spread([])


def test_area_share_by_status_weighted_by_area_not_count():
    children = [
        ChildUnit("A", established_area_ha=1, target_area_ha=1, yield_kg_ha=1, area_ha=900),  # big, delayed
        ChildUnit("B", established_area_ha=1, target_area_ha=1, yield_kg_ha=1, area_ha=50),   # small, on_track
        ChildUnit("C", established_area_ha=1, target_area_ha=1, yield_kg_ha=1, area_ha=50),   # small, on_track
    ]
    status_map = {"A": "delayed", "B": "on_track", "C": "on_track"}
    shares = area_share_by_status(children, lambda c: status_map[c.admin_id])
    # by COUNT, on_track would be 2/3 = 67%; by AREA it must be only 10%
    assert shares["on_track"] == pytest.approx(10.0)
    assert shares["delayed"] == pytest.approx(90.0)
