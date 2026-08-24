from collections import Counter
from app.services.card_manifest import CardManifestService


def test_total_card_count_is_32():
    m = CardManifestService()
    assert len(m.all_cards()) == 32


def test_tier_distribution():
    m = CardManifestService()
    counts = Counter(c["tier"] for c in m.all_cards())
    assert counts[1] == 9
    assert counts[2] == 15
    assert counts[3] == 8


def test_tier1_cards_have_no_hard_requirements_besides_core_fields():
    """Tier-1 cards are supposed to be the 'always visible' 10-second answer --
    they should degrade gracefully, not silently vanish because of one
    optional field."""
    m = CardManifestService()
    tier1 = m.by_tier(1)
    assert all(c["theme"] in {"sowing", "yield", "cross_theme"} for c in tier1)


def test_renderable_cards_excludes_missing_requirements():
    m = CardManifestService()
    minimal_snapshot = {"situation": {"x": 1}}
    renderable = m.renderable_cards(minimal_snapshot)
    ids = {c["card_id"] for c in renderable}
    assert "agri_situation" in ids
    assert "sowing_progress" not in ids  # requires sowing.progress_pct which is absent


def test_renderable_cards_includes_full_requirements_when_present():
    m = CardManifestService()
    full_snapshot = {
        "situation": {"x": 1},
        "sowing": {"progress_pct": 50, "target_area_ha": 100, "stage_distribution": {"a": 1},
                    "confidence": {}, "lineage": {"computation_trace_id": "abc", "sources": [{"a": 1}]},
                    "spatial_support": {"total_pixels": 1}},
        "yield_performance": {"yield_gap_kg_ha": 10, "counterfactual_tier": "L2",
                                "production_gap_mt": 5, "attainable_yield_kg_ha": 100,
                                "historical_expected_yield_kg_ha": 90, "estimated_yield_kg_ha": 80,
                                "estimated_yield_kg_ha_2": None},
    }
    renderable = m.renderable_cards(full_snapshot)
    ids = {c["card_id"] for c in renderable}
    assert "sowing_progress" in ids
    assert "yield_gap" in ids
    assert "lineage_trace" in ids
