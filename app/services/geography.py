import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


class UnknownAdminUnit(ValueError):
    pass


class GeographyService:
    def __init__(self):
        self._geo = json.loads((_DATA_DIR / "geography.json").read_text())
        self._crosswalk = json.loads((_DATA_DIR / "geography_crosswalk.json").read_text())
        self._by_id = {u["admin_id"]: u for u in self._geo["admin1"]}
        for u in self._geo.get("admin2_mvp_pilot", []):
            self._by_id[u["admin_id"]] = u

    # ---- basic lookups -------------------------------------------------
    def countries(self) -> list[dict]:
        return self._geo["countries"]

    def schema_for(self, country_id: str) -> dict:
        return self._geo["schemas"][country_id]

    def get_unit(self, admin_id: str) -> dict:
        unit = self._by_id.get(admin_id)
        if unit is None:
            raise UnknownAdminUnit(admin_id)
        return unit

    def admin1_for_country(self, country_id: str, include_hidden: bool = False) -> list[dict]:
        units = [u for u in self._geo["admin1"] if u["country_id"] == country_id]
        if not include_hidden:
            units = [u for u in units if not u.get("hidden_from_picker", False)]
        return units

    def children(self, admin_id: str) -> list[dict]:
        return [u for u in self._by_id.values() if u.get("parent_admin_id") == admin_id]

    # ---- resolution rules (§2.1/§2.2 of the review doc) -----------------
    def resolve(self, admin_id: str) -> dict:
        """Resolves a merged unit to its live target (Daman and Diu -> DNH&DD),
        and returns the max drill-down depth actually supported for this unit."""
        unit = self.get_unit(admin_id)
        if unit.get("merged_into"):
            unit = self.get_unit(unit["merged_into"])

        breadcrumb = self._breadcrumb(unit)
        return {
            "admin_id": unit["admin_id"],
            "country_id": unit["country_id"],
            "admin_level": unit["admin_level"],
            "canonical_name": unit["canonical_name"],
            "breadcrumb": breadcrumb,
            "max_supported_depth": unit.get("max_supported_depth", unit["admin_level"]),
            "depth_limited_reason": unit.get("depth_limited_reason"),
        }

    def _breadcrumb(self, unit: dict) -> list[str]:
        country_name = next(c["name"] for c in self._geo["countries"] if c["country_id"] == unit["country_id"])
        chain = [unit["canonical_name"]]
        cur = unit
        while cur.get("parent_admin_id"):
            cur = self.get_unit(cur["parent_admin_id"])
            chain.append(cur["canonical_name"])
        chain.append(country_name)
        return list(reversed(chain))

    # ---- crosswalk (legacy province/region names -> real admin_ids) -----
    def crosswalk_groups(self, country_id: str) -> list[dict]:
        return [g for g in self._crosswalk["groups"] if g["country_id"] == country_id]

    def resolve_legacy_name(self, country_id: str, legacy_name: str) -> list[str]:
        """Resolves a legacy display name (e.g. Kenya's 'Rift Valley' province)
        to the list of real, clickable admin_ids it groups. Returns [] if the
        legacy name doesn't map to a known group -- callers must not fall back
        to treating the legacy name itself as an admin_id."""
        for g in self.crosswalk_groups(country_id):
            if g["legacy_name"].lower() == legacy_name.lower():
                return [a for a in g["maps_to_admin_ids"] if not a.startswith("placeholder")]
        return []

    def ethiopia_boundary_status(self) -> dict:
        return self._crosswalk["ethiopia_boundary_staleness_flag"]
