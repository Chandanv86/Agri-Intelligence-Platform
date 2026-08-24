from .base import CountryAdapter


class KenyaAdapter(CountryAdapter):
    country_id = "KEN"

    def hierarchy_level_names(self) -> dict[str, str]:
        return {"1": "County", "2": "Constituency", "3": "Ward"}

    def crop_mask_primary_source(self) -> str:
        return "worldcereal"

    def crop_mask_fallback_source(self) -> str:
        return "worldcereal"

    def price_currency(self) -> str:
        return "KES"

    def price_granularity_note(self) -> str:
        return "Moderate: national/regional market price bulletins; county-level series thinner than India's."

    def rainfall_source(self) -> str:
        return "chirps"
