import pytest
from app.services.country_adapters.registry import get_adapter, all_country_ids


def test_all_six_countries_registered():
    assert set(all_country_ids()) == {"IND", "KEN", "UGA", "TZA", "ETH", "ZAF"}


def test_india_is_only_amed_supported_country():
    for cid in all_country_ids():
        a = get_adapter(cid)
        expected = cid == "IND"
        assert a.supports_field_level_crop_source() == expected


def test_india_hierarchy_matches_uploaded_admin_table():
    a = get_adapter("IND")
    levels = a.hierarchy_level_names()
    assert levels["1"] == "State / UT"
    assert levels["2"] == "District"
    assert levels["3"] == "Sub-district"
    assert levels["4"] == "Village"


def test_kenya_hierarchy_has_no_village_layer():
    a = get_adapter("KEN")
    levels = a.hierarchy_level_names()
    assert "4" not in levels
    assert levels["3"] == "Ward"


def test_each_country_has_distinct_currency():
    currencies = {get_adapter(cid).price_currency() for cid in all_country_ids()}
    assert len(currencies) == 6  # INR, KES, UGX, TZS, ETB, ZAR -- all distinct


def test_unknown_country_raises():
    with pytest.raises(ValueError):
        get_adapter("XXX")


def test_ethiopia_flags_its_own_boundary_status():
    a = get_adapter("ETH")
    assert a.boundary_status() == "unresolved_blocker_for_ethiopia_v1"
