from .base import CountryAdapter


class TanzaniaAdapter(CountryAdapter):
    country_id = "TZA"

    def hierarchy_level_names(self) -> dict[str, str]:
        return {"1": "Region", "2": "District", "3": "Ward"}

    def crop_mask_primary_source(self) -> str:
        return "worldcereal"

    def crop_mask_fallback_source(self) -> str:
        return "worldcereal"

    def price_currency(self) -> str:
        return "TZS"

    def price_granularity_note(self) -> str:
        return "Thin: regional market monitoring exists but is less consistent than India's mandi network."

    def rainfall_source(self) -> str:
        return "chirps"
