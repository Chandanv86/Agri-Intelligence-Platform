from pydantic import BaseModel


class AdminLevelSchema(BaseModel):
    """Per-country hierarchy definition. The backend must never assume
    level_1 == state; it always resolves this from the registry."""
    country_id: str
    level_names: dict[str, str]          # {"1": "State / UT", "2": "District", ...}
    expected_level1_count: int
    supplied_level1_count: int
    count_status: str                    # ok | mismatch
    max_villageable_states: list[str] = []   # for India: states with village-level geometry
    village_unsupported_states: list[str] = []


class AdminUnit(BaseModel):
    admin_id: str
    country_id: str
    parent_admin_id: str | None
    admin_level: int
    admin_level_name: str
    canonical_name: str
    aliases: list[str] = []
    geometry_source: str = "GADM"
    geometry_version: str = "unversioned"
    hidden_from_picker: bool = False
    merged_into: str | None = None


class CrosswalkGroup(BaseModel):
    """Maps a legacy/officially-used display name (e.g. a Kenyan province, a
    Ugandan region) onto the set of real analytical admin units (counties,
    districts) that the map actually renders and clicks against."""
    country_id: str
    legacy_id: str
    legacy_name: str
    legacy_kind: str          # e.g. "province", "region"
    maps_to_admin_ids: list[str]
    note: str = ""


class GeographyResolution(BaseModel):
    """What /geography/resolve returns for a clicked or selected unit."""
    admin_id: str
    country_id: str
    admin_level: int
    canonical_name: str
    breadcrumb: list[str]          # ["India", "Bihar", "Patna"]
    max_supported_depth: int
    depth_limited_reason: str | None = None
