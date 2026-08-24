import pytest
from app.services.geography import GeographyService, UnknownAdminUnit


@pytest.fixture
def geo():
    return GeographyService()


def test_countries_present(geo):
    ids = {c["country_id"] for c in geo.countries()}
    assert ids == {"IND", "KEN", "UGA", "TZA", "ETH", "ZAF"}


def test_daman_and_diu_hidden_and_resolves_to_merged_unit(geo):
    admin1 = geo.admin1_for_country("IND")
    ids = {u["admin_id"] for u in admin1}
    assert "IND-ADMIN1-DAMAN-AND-DIU" not in ids  # hidden from picker

    resolved = geo.resolve("IND-ADMIN1-DAMAN-AND-DIU")
    assert resolved["admin_id"] == "IND-ADMIN1-DADRA-AND-NAGAR-HAVELI"


def test_village_unsupported_states_capped_depth(geo):
    for name_slug in ["ARUNACHAL-PRADESH", "MANIPUR", "NAGALAND"]:
        r = geo.resolve(f"IND-ADMIN1-{name_slug}")
        assert r["max_supported_depth"] == 3
        assert r["depth_limited_reason"] is not None


def test_village_supported_states_full_depth(geo):
    r = geo.resolve("IND-ADMIN1-PUNJAB")
    assert r["max_supported_depth"] == 4
    assert r["depth_limited_reason"] is None


def test_unknown_admin_id_raises(geo):
    with pytest.raises(UnknownAdminUnit):
        geo.resolve("IND-ADMIN1-ATLANTIS")


def test_kenya_legacy_province_resolves_to_multiple_counties(geo):
    counties = geo.resolve_legacy_name("KEN", "Rift Valley")
    assert len(counties) > 5
    assert all(c.startswith("KEN-ADMIN1-") for c in counties)


def test_kenya_unknown_legacy_name_returns_empty(geo):
    assert geo.resolve_legacy_name("KEN", "Not A Real Province") == []


def test_uganda_crosswalk_is_honestly_flagged_as_placeholder(geo):
    """This is a deliberate assertion of current project state, not a bug:
    the Uganda region->district crosswalk has NOT been verified against an
    authoritative UBOS source yet, and the data says so rather than shipping
    a fabricated mapping (see geography_crosswalk.json note)."""
    groups = geo.crosswalk_groups("UGA")
    assert len(groups) == 4
    for g in groups:
        assert g["maps_to_admin_ids"][0].startswith("placeholder")


def test_ethiopia_boundary_staleness_flag_present(geo):
    flag = geo.ethiopia_boundary_status()
    assert flag["status"] == "unresolved_blocker_for_ethiopia_v1"
    assert "Sidama" in flag["issue"]


def test_breadcrumb_for_mvp_district(geo):
    r = geo.resolve("IND-ADMIN2-PUNJAB-LUDHIANA")
    assert r["breadcrumb"] == ["India", "Punjab", "Ludhiana"]


def test_children_of_bihar_are_mvp_pilot_districts(geo):
    kids = geo.children("IND-ADMIN1-BIHAR")
    names = {k["canonical_name"] for k in kids}
    assert "Patna" in names
    assert len(kids) == 10
