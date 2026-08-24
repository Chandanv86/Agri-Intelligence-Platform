from .base import CountryAdapter


class EthiopiaAdapter(CountryAdapter):
    country_id = "ETH"

    def hierarchy_level_names(self) -> dict[str, str]:
        return {"1": "Region", "2": "Zone", "3": "Woreda"}

    def crop_mask_primary_source(self) -> str:
        return "worldcereal"

    def crop_mask_fallback_source(self) -> str:
        return "worldcereal"

    def price_currency(self) -> str:
        return "ETB"

    def price_granularity_note(self) -> str:
        return "Thin: sparser market reporting; also see the unresolved boundary-staleness blocker in geography_crosswalk.json."

    def rainfall_source(self) -> str:
        return "chirps"

    def boundary_status(self) -> str:
        return "unresolved_blocker_for_ethiopia_v1"
