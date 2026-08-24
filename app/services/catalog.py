import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


class CatalogService:
    def __init__(self):
        self._crops = json.loads((_DATA_DIR / "crops.json").read_text())["crops"]
        self._seasons = json.loads((_DATA_DIR / "seasons.json").read_text())["seasons"]

    def crops(self) -> list[dict]:
        return self._crops

    def crop(self, crop_id: str) -> dict:
        return next(c for c in self._crops if c["crop_id"] == crop_id)

    def seasons_for(self, country_id: str, crop_id: str | None = None) -> list[dict]:
        out = [s for s in self._seasons if s["country_id"] == country_id]
        if crop_id:
            out = [s for s in out if s["crop_id"] == crop_id]
        return out
