import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"
_ALT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


def _load() -> list[dict]:
    path = _ALT_DATA_DIR / "card_manifest.json"
    return json.loads(path.read_text())["cards"]


class CardManifestService:
    def __init__(self):
        self._cards = _load()

    def all_cards(self) -> list[dict]:
        return self._cards

    def by_tier(self, tier: int) -> list[dict]:
        return [c for c in self._cards if c["tier"] == tier]

    def by_theme(self, theme: str) -> list[dict]:
        return [c for c in self._cards if c["theme"] == theme]

    def _get(self, snapshot: dict, dotted_path: str):
        cur = snapshot
        for part in dotted_path.split("."):
            if cur is None:
                return None
            cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
        return cur

    def renderable_cards(self, snapshot: dict) -> list[dict]:
        """Filters the manifest down to cards whose `requires` fields are all
        present in this snapshot. This is what stops a card from rendering an
        empty/undefined box when a country lacks the underlying evidence
        (e.g. a Tier-2 stage_distribution card for a country without that
        classifier output yet)."""
        out = []
        for card in self._cards:
            ok = True
            for req in card.get("requires", []):
                if self._get(snapshot, req) in (None, [], {}):
                    ok = False
                    break
            if ok:
                out.append(card)
        return out
