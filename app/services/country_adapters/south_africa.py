from .base import CountryAdapter


class SouthAfricaAdapter(CountryAdapter):
    country_id = "ZAF"

    def hierarchy_level_names(self) -> dict[str, str]:
        return {"1": "Province", "2": "District", "3": "Municipality"}

    def crop_mask_primary_source(self) -> str:
        return "worldcereal"

    def crop_mask_fallback_source(self) -> str:
        return "worldcereal"

    def price_currency(self) -> str:
        return "ZAR"

    def price_granularity_note(self) -> str:
        return "Moderate: SAFEX/AMT price series available for maize; more commercialized-farming context than East Africa."

    def rainfall_source(self) -> str:
        return "era5"
