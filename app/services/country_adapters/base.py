"""§122 of the review doc: CountryAdapter is the seam that keeps
country-specific agricultural context (calendars, hierarchy, price source,
crop-mask primary source) out of conditionals scattered across the codebase."""

from abc import ABC, abstractmethod


class CountryAdapter(ABC):
    country_id: str

    @abstractmethod
    def hierarchy_level_names(self) -> dict[str, str]:
        """{'1': 'State / UT', '2': 'District', ...}"""

    @abstractmethod
    def crop_mask_primary_source(self) -> str:
        """'amed' | 'worldcereal'"""

    @abstractmethod
    def crop_mask_fallback_source(self) -> str:
        ...

    @abstractmethod
    def price_currency(self) -> str:
        ...

    @abstractmethod
    def price_granularity_note(self) -> str:
        """Human-readable statement of how granular price reporting actually
        is in this country -- feeds the confidence model, per §2.5."""

    @abstractmethod
    def rainfall_source(self) -> str:
        """'chirps' | 'era5' -- which is the stronger context source here."""

    def supports_field_level_crop_source(self) -> bool:
        return self.crop_mask_primary_source() == "amed"
