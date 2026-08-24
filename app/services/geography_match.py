"""Reconciles names as they appear in REAL open boundary geometry (sourced
from Highcharts map-collection-dist / geohacker-india, see
docs/BOUNDARY_DATA_SOURCES.md) against this project's own admin_id registry
in geography.json. These two things were authored independently and don't
always agree on spelling or on which entities exist -- see the alias table
below and docs/KNOWN_LIMITATIONS.md for the concrete list of divergences
this uncovered (India: Ladakh has no registry entry; Kenya: the only free
boundary geometry available is the 8 legacy provinces, not the 47 counties)."""

from .geography import GeographyService

# observed geometry name -> canonical registry name, per country.
# Only entries where the two sources actually disagree need to be listed;
# everything else matches by exact case-insensitive name.
_ALIASES: dict[str, dict[str, str]] = {
    "IND": {
        "andaman and nicobar islands": "Andaman and Nicobar",
        "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli",
        "delhi": "NCT of Delhi",
        # "Ladakh" intentionally has NO alias: it was split from Jammu and
        # Kashmir in 2019 and has no admin_id in this project's registry yet.
    },
    "KEN": {
        "north-eastern": "North Eastern",
    },
}

# Real boundary geometry currently available is coarser/finer than this
# project's hand-authored hierarchy for these two countries -- see
# docs/KNOWN_LIMITATIONS.md. The map shows what real geometry exists;
# analytical admin_ids for the "true" level are reached via the crosswalk
# list UI instead of a map click for these two.
GEOMETRY_LEVEL_NOTE: dict[str, str] = {
    "KEN": "Only the 8 legacy provinces have free boundary geometry available; "
           "the 47 real counties are offered as a list (via the crosswalk) "
           "after clicking a province, not as map polygons.",
    "UGA": "This boundary source's 112 districts are more current than the "
           "58-district figure originally supplied; most will not yet match "
           "an admin_id in the registry and will show as 'not yet linked'.",
}


class GeographyMatchService:
    def __init__(self, geography: GeographyService | None = None):
        self.geography = geography or GeographyService()

    def match(self, country_id: str, observed_name: str) -> str | None:
        units = self.geography.admin1_for_country(country_id, include_hidden=True)
        by_name = {u["canonical_name"].strip().lower(): u["admin_id"] for u in units}

        alias_target = _ALIASES.get(country_id, {}).get(observed_name.strip().lower())
        lookup_name = (alias_target or observed_name).strip().lower()

        admin_id = by_name.get(lookup_name)
        if admin_id is None:
            return None
        resolved = self.geography.resolve(admin_id)
        return resolved["admin_id"]  # follows merged_into if applicable

    def match_many(self, country_id: str, observed_names: list[str]) -> dict[str, str | None]:
        return {name: self.match(country_id, name) for name in observed_names}
