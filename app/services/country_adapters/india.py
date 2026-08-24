from .base import CountryAdapter


class IndiaAdapter(CountryAdapter):
    country_id = "IND"

    def hierarchy_level_names(self) -> dict[str, str]:
        return {"1": "State / UT", "2": "District", "3": "Sub-district", "4": "Village"}

    def crop_mask_primary_source(self) -> str:
        return "amed"

    def crop_mask_fallback_source(self) -> str:
        return "worldcereal"

    def price_currency(self) -> str:
        return "INR"

    def price_granularity_note(self) -> str:
        return "Strong: MSP + district-level modal mandi prices (Agmarknet) generally available."

    def rainfall_source(self) -> str:
        return "chirps"
