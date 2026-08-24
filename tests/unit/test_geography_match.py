import pytest
from app.services.geography_match import GeographyMatchService, GEOMETRY_LEVEL_NOTE


@pytest.fixture
def matcher():
    return GeographyMatchService()


def test_exact_name_match(matcher):
    assert matcher.match("IND", "Punjab") == "IND-ADMIN1-PUNJAB"
    assert matcher.match("IND", "Bihar") == "IND-ADMIN1-BIHAR"


def test_case_insensitive_match(matcher):
    assert matcher.match("IND", "punjab") == "IND-ADMIN1-PUNJAB"


def test_alias_table_resolves_boundary_source_naming_differences(matcher):
    assert matcher.match("IND", "Delhi") == "IND-ADMIN1-NCT-OF-DELHI"
    assert matcher.match("IND", "Andaman and Nicobar Islands") == "IND-ADMIN1-ANDAMAN-AND-NICOBAR"


def test_dadra_nagar_haveli_daman_diu_merged_name_resolves_to_merged_target(matcher):
    result = matcher.match("IND", "Dadra and Nagar Haveli and Daman and Diu")
    assert result == "IND-ADMIN1-DADRA-AND-NAGAR-HAVELI"


def test_ladakh_has_no_registry_entry_and_returns_none(matcher):
    """Ladakh was split from Jammu and Kashmir in 2019 and genuinely isn't in
    this project's admin registry yet -- returning None here (not guessing,
    not erroring) is the correct, honest behavior."""
    assert matcher.match("IND", "Ladakh") == None


def test_kenya_legacy_provinces_do_not_match_county_registry(matcher):
    """Kenya's only free boundary geometry is at the (legacy) province level,
    which deliberately has no admin_id in the registry -- provinces are a
    display-only grouping over the real county admin_ids."""
    assert matcher.match("KEN", "Coast") is None
    assert matcher.match("KEN", "Nyanza") is None


def test_kenya_hyphen_alias_still_resolves_to_none_consistently(matcher):
    # Even after the North-Eastern -> North Eastern alias fires, "North Eastern"
    # itself still isn't a county-level admin_id, so this must stay None too.
    assert matcher.match("KEN", "North-Eastern") is None


def test_match_many_batches_correctly(matcher):
    result = matcher.match_many("IND", ["Punjab", "Bihar", "Ladakh"])
    assert result["Punjab"] == "IND-ADMIN1-PUNJAB"
    assert result["Bihar"] == "IND-ADMIN1-BIHAR"
    assert result["Ladakh"] is None


def test_geometry_level_note_present_for_kenya_and_uganda_only():
    assert "Kenya" not in GEOMETRY_LEVEL_NOTE  # keyed by country_id not name
    assert GEOMETRY_LEVEL_NOTE["KEN"]
    assert GEOMETRY_LEVEL_NOTE["UGA"]
    assert "TZA" not in GEOMETRY_LEVEL_NOTE
