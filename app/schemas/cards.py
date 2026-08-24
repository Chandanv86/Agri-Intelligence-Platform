from pydantic import BaseModel


class CardManifestEntry(BaseModel):
    """One row of the canonical 32-card stack (see docs/ARCHITECTURE.md §4).
    The frontend renders purely from this manifest + the snapshot payload —
    card tiering/ordering is never hardcoded in frontend components."""
    card_id: str
    theme: str          # sowing | yield | cross_theme
    tier: int            # 1 = always visible, 2 = expandable, 3 = advanced
    title: str
    snapshot_path: str   # dotted path into the AgriSnapshot payload this card reads
    requires: list[str] = []   # snapshot fields that must be non-null for this card to render
    visualization: str   # number | bar | stacked_bar | line_envelope | waterfall | table | matrix
