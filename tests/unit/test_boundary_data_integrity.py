"""Regression test for a real bug caught during development: the first-choice
boundary source (Highcharts map-collection-dist's custom/world.geo.json and
countries/*/*-all.geo.json) turned out to be in EPSG:54003 (Miller projection)
despite the .geo.json extension, not WGS84 lng/lat -- every map click silently
missed every feature because coordinates like [6818, 7133] aren't valid
lng/lat. Switching to Natural Earth (which correctly declares and uses
CRS84) fixed it. This test makes sure no future boundary file update can
reintroduce a non-WGS84 file without the test suite catching it immediately,
rather than only being discoverable by manually clicking the map."""

import json
from pathlib import Path

BOUNDARIES_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "boundaries"


def _iter_boundary_files():
    yield from BOUNDARIES_DIR.glob("*.geojson")
    yield from (BOUNDARIES_DIR / "india_districts").glob("*.geojson")


def _flatten_coords(coords):
    if isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from _flatten_coords(c)


def test_boundary_directory_is_not_empty():
    files = list(_iter_boundary_files())
    assert len(files) >= 40, f"expected the full boundary set, found {len(files)}"


def test_every_boundary_file_has_valid_wgs84_coordinates():
    checked = 0
    for path in _iter_boundary_files():
        data = json.loads(path.read_text())
        for feature in data["features"]:
            geometry = feature.get("geometry")
            assert geometry is not None and geometry.get("coordinates") is not None, (
                f"{path.name}: feature with null geometry ({feature.get('properties')}) -- "
                f"this exact failure mode (from over-aggressive simplification) was caught "
                f"and fixed for Lakshadweep during development; a new null geometry means "
                f"a boundary file was regenerated without checking for this again."
            )
            for x, y in _flatten_coords(geometry["coordinates"]):
                assert -180 <= x <= 180, (
                    f"{path.name}: longitude {x} out of range -- looks like a non-WGS84 "
                    f"projected coordinate system slipped back in (see docs/BOUNDARY_DATA_SOURCES.md)"
                )
                assert -90 <= y <= 90, f"{path.name}: latitude {y} out of range"
                checked += 1
    assert checked > 1000, "sanity check that we actually walked real geometry, not empty files"


def test_key_mvp_district_files_present_and_named_correctly():
    manifest = json.loads((BOUNDARIES_DIR / "india_districts" / "_manifest.json").read_text())
    assert "punjab" in manifest
    assert "bihar" in manifest
    assert manifest["punjab"]["district_count"] > 0
    assert manifest["bihar"]["district_count"] > 0


def test_world_supported_countries_has_exactly_six_features_with_iso_a3():
    data = json.loads((BOUNDARIES_DIR / "world_supported_countries.geojson").read_text())
    isos = {f["properties"]["iso-a3"] for f in data["features"]}
    assert isos == {"IND", "KEN", "UGA", "TZA", "ETH", "ZAF"}


def test_admin1_files_exist_for_all_six_countries():
    for fname in ["admin1_india.geojson", "admin1_kenya.geojson", "admin1_uganda.geojson",
                  "admin1_tanzania.geojson", "admin1_ethiopia.geojson", "admin1_south_africa.geojson"]:
        path = BOUNDARIES_DIR / fname
        assert path.exists(), fname
        data = json.loads(path.read_text())
        assert len(data["features"]) > 0
        assert "name" in data["features"][0]["properties"]
