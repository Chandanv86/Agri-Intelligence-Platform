from .base import CountryAdapter


class UgandaAdapter(CountryAdapter):
    country_id = "UGA"

    def hierarchy_level_names(self) -> dict[str, str]:
        return {"1": "District", "2": "County", "3": "Sub-county", "4": "Village"}

    def crop_mask_primary_source(self) -> str:
        return "worldcereal"

    def crop_mask_fallback_source(self) -> str:
        return "worldcereal"

    def price_currency(self) -> str:
        return "UGX"

    def price_granularity_note(self) -> str:
        return "Moderate: UBOS market bulletins exist but district-level series are thinner than India's."

    def rainfall_source(self) -> str:
        return "chirps"
