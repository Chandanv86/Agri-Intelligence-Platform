"""Google DeepMind AMED (Agricultural Monitoring and Event Detection) API
connector -- see Card_Architecture_Final_Review_and_Gaps.md §2.6/§6.

CRITICAL CONSTRAINT: AMED is currently INDIA-ONLY and requires Google to
allowlist your GWCID before the API key works (per agri.withgoogle.com/faq).
This connector must never be called for a non-India country -- it raises
AmedNotAvailableForCountry immediately rather than making a request that
would fail anyway, so the failure is explicit and typed instead of a generic
HTTP error surfacing three layers up.
"""

import httpx


class AmedNotConfigured(RuntimeError):
    pass


class AmedNotAvailableForCountry(RuntimeError):
    pass


_SUPPORTED_COUNTRIES = {"IND"}


class AmedClient:
    def __init__(self, api_key: str | None = None, enabled: bool = False,
                 base_url: str = "https://agri.googleapis.com"):
        self.api_key = api_key
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")

    def configured(self) -> bool:
        return self.enabled and bool(self.api_key)

    def supports_country(self, country_id: str) -> bool:
        return country_id in _SUPPORTED_COUNTRIES

    async def field_crop_predictions(self, *, country_id: str, lat: float, lng: float) -> dict:
        """Returns field-level crop type + season history for the S2 cell
        containing (lat, lng). See docs/KNOWN_LIMITATIONS.md for the S2-cell
        addressing scheme AMED uses instead of arbitrary polygons."""
        if not self.supports_country(country_id):
            raise AmedNotAvailableForCountry(
                f"AMED does not currently cover {country_id}; use WorldCereal/Dynamic World instead."
            )
        if not self.configured():
            raise AmedNotConfigured("AMED_API_KEY not set or AMED_ENABLED is false")

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.base_url}/v1/amed:predict",
                params={"lat": lat, "lng": lng, "key": self.api_key},
            )
            r.raise_for_status()
            return r.json()
