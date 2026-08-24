"""Copernicus Data Space Ecosystem STAC client -- discovery only. §53/§60 of
the review doc: STAC should be a first-class discovery layer in front of
whichever asset-access method (Sentinel Hub, direct COG, GEE) does the actual
pixel work, so scene selection isn't hardcoded per provider."""

import httpx


class CDSESTACClient:
    def __init__(self, endpoint: str = "https://stac.dataspace.copernicus.eu/v1/", timeout: float = 30):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    async def search(
        self,
        *,
        collections: list[str],
        bbox: list[float] | None = None,
        datetime_range: str | None = None,
        limit: int = 20,
        query: dict | None = None,
    ) -> dict:
        payload: dict = {"collections": collections, "limit": limit}
        if bbox:
            payload["bbox"] = bbox
        if datetime_range:
            payload["datetime"] = datetime_range
        if query:
            payload["query"] = query
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.endpoint}/search", json=payload)
            r.raise_for_status()
            return r.json()

    async def latest_cloud_free_scene(
        self, *, bbox: list[float], datetime_range: str, max_cloud_pct: float = 20.0
    ) -> dict | None:
        """Card 'Observation Gap' (§100): finds the most recent usable optical
        scene so the platform can report an honest observation-age number
        instead of implying every card is as fresh as 'today'."""
        result = await self.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime_range=datetime_range,
            limit=50,
            query={"eo:cloud_cover": {"lt": max_cloud_pct}},
        )
        features = result.get("features", [])
        if not features:
            return None
        return max(features, key=lambda f: f["properties"]["datetime"])
