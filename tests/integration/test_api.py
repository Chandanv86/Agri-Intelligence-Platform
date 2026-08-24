import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "Agricultural Intelligence Platform" in r.text


def test_list_countries():
    r = client.get("/api/v1/geography/countries")
    assert r.status_code == 200
    assert len(r.json()) == 6


def test_admin1_excludes_hidden_daman_diu():
    r = client.get("/api/v1/geography/IND/admin1")
    ids = {u["admin_id"] for u in r.json()}
    assert "IND-ADMIN1-DAMAN-AND-DIU" not in ids


def test_resolve_unknown_admin_returns_404():
    r = client.get("/api/v1/geography/resolve/NOT-A-REAL-ID")
    assert r.status_code == 404


def test_children_of_punjab_returns_mvp_districts():
    r = client.get("/api/v1/geography/IND-ADMIN1-PUNJAB/children")
    assert r.status_code == 200
    assert len(r.json()) == 10


def test_snapshot_happy_path_ludhiana():
    r = client.get(
        "/api/v1/agri/areas/IND-ADMIN2-PUNJAB-LUDHIANA/snapshot",
        params={"crop_id": "rice", "season_id": "IND-2026-kharif-rice"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot"]["data_status"] == "DEMO"
    assert body["snapshot"]["identity"]["breadcrumb"] == ["India", "Punjab", "Ludhiana"]
    assert len(body["renderable_cards"]) == 32
    # Tier-1 situation card values must be internally consistent
    situation = body["snapshot"]["situation"]
    sowing = body["snapshot"]["sowing"]
    assert situation["sowing_deviation_pp"] == sowing["deviation"]["value"]


def test_snapshot_happy_path_patna():
    r = client.get(
        "/api/v1/agri/areas/IND-ADMIN2-BIHAR-PATNA/snapshot",
        params={"crop_id": "rice", "season_id": "IND-2026-kharif-rice"},
    )
    assert r.status_code == 200
    assert r.json()["snapshot"]["identity"]["canonical_name"] == "Patna"


def test_snapshot_missing_fixture_returns_501_not_fake_data():
    """This is the platform's most important negative test: an area outside
    the MVP pilot must fail loudly (501), never silently return plausible
    but fabricated numbers."""
    r = client.get(
        "/api/v1/agri/areas/IND-ADMIN1-NCT-OF-DELHI/snapshot",
        params={"crop_id": "rice", "season_id": "IND-2026-kharif-rice"},
    )
    assert r.status_code == 501


def test_card_manifest_endpoint_tier_filter():
    r = client.get("/api/v1/cards/manifest", params={"tier": 1})
    assert r.status_code == 200
    assert len(r.json()) == 9


def test_country_adapters_endpoint_lists_six():
    r = client.get("/api/v1/countries/adapters")
    assert r.status_code == 200
    assert len(r.json()) == 6


def test_kenya_crosswalk_endpoint():
    r = client.get("/api/v1/geography/KEN/crosswalk")
    assert r.status_code == 200
    assert len(r.json()) == 8


def test_geography_match_endpoint():
    r = client.post("/api/v1/geography/match", json={"country_id": "IND", "names": ["Punjab", "Ladakh"]})
    assert r.status_code == 200
    body = r.json()
    assert body["matches"]["Punjab"] == "IND-ADMIN1-PUNJAB"
    assert body["matches"]["Ladakh"] is None


def test_geography_match_kenya_returns_geometry_level_note():
    r = client.post("/api/v1/geography/match", json={"country_id": "KEN", "names": ["Coast"]})
    assert r.status_code == 200
    body = r.json()
    assert body["matches"]["Coast"] is None
    assert "counties" in body["geometry_level_note"]


def test_legacy_groups_endpoint():
    r = client.get("/api/v1/geography/KEN/legacy-groups")
    assert r.status_code == 200
    assert len(r.json()) == 8


def test_boundary_static_files_are_served():
    for path in [
        "/static/boundaries/world_supported_countries.geojson",
        "/static/boundaries/admin1_india.geojson",
        "/static/boundaries/admin1_kenya.geojson",
        "/static/boundaries/india_districts/punjab.geojson",
        "/static/boundaries/india_districts/bihar.geojson",
        "/static/boundaries/india_districts/_manifest.json",
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
