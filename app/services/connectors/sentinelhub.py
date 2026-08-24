"""Sentinel Hub Statistics API client (Copernicus Data Space Ecosystem).
Real OAuth2 client-credentials flow + real /api/v1/statistics contract.
Raises explicitly if credentials are absent -- callers must catch this and
mark the resulting metric data_status=DEMO, never silently fabricate a value."""

import math

import httpx


class SentinelHubNotConfigured(RuntimeError):
    pass


class SentinelHubRequestFailed(RuntimeError):
    """Carries the API's own error body. Sentinel Hub explains *why* a request
    was rejected in the response payload, and httpx's raise_for_status()
    discards it -- which turns a precise, fixable error into a bare 400."""


# Copernicus Data Space Ecosystem issues OAuth tokens from its Keycloak
# identity host, NOT from the Sentinel Hub API host. Posting credentials to
# https://sh.dataspace.copernicus.eu/oauth/token answers 503.
_CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)


class SentinelHubStatisticsClient:
    def __init__(self, base_url: str, client_id: str | None = None,
                 client_secret: str | None = None, token_url: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url or self._default_token_url(self.base_url)

    @staticmethod
    def _default_token_url(base_url: str) -> str:
        """Picks the right token endpoint for the deployment behind base_url.
        Override with SENTINELHUB_TOKEN_URL if your deployment differs."""
        if "dataspace.copernicus.eu" in base_url:
            return _CDSE_TOKEN_URL
        # Classic Sentinel Hub (services.sentinel-hub.com) serves it inline.
        return f"{base_url}/oauth/token"

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def token(self) -> str:
        if not self.configured():
            raise SentinelHubNotConfigured("Sentinel Hub credentials are not configured")
        async with httpx.AsyncClient(timeout=30) as c:
            # client_secret_post form: accepted by both Keycloak (CDSE) and
            # classic Sentinel Hub, unlike HTTP Basic which Keycloak rejects
            # unless the client is explicitly configured for it.
            r = await c.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return r.json()["access_token"]

    async def statistics(self, payload: dict) -> dict:
        """payload follows the Sentinel Hub Statistical API contract: input
        (bounds + data collection), aggregation (time range, resx/resy,
        evalscript), and calculations (stats requested)."""
        token = await self.token()
        url = f"{self.base_url}/api/v1/statistics"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json=payload, headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                raise SentinelHubRequestFailed(
                    f"Sentinel Hub {r.status_code} for {url}: {r.text[:1200]}"
                )
            return r.json()

    @staticmethod
    def resolution_for_bbox(bbox: list[float], max_dim_px: int = 2000) -> float:
        """Sentinel Hub caps the pixel grid per Statistics request. A whole
        district at 10 m is tens of millions of pixels, which the API rejects
        with a bare 400 -- so scale the resolution to the AOI instead of
        hardcoding 10 m. For a district-wide MEAN this costs no useful accuracy.
        """
        mean_lat = (bbox[1] + bbox[3]) / 2.0
        width_m = abs(bbox[2] - bbox[0]) * 111_320 * math.cos(math.radians(mean_lat))
        height_m = abs(bbox[3] - bbox[1]) * 110_574
        largest = max(width_m, height_m)
        if largest <= 0 or max_dim_px <= 0:
            return 10.0
        return float(max(10.0, math.ceil(largest / max_dim_px)))

    @staticmethod
    def ndvi_timeseries_payload(bbox: list[float], date_from: str, date_to: str) -> dict:
        """Builds a real Statistics API request body for an NDVI time series
        over a bounding box using harmonized Sentinel-2 L2A."""
        evalscript = """
//VERSION=3
function setup() {
  return {input: [{bands: ["B04","B08","SCL","dataMask"]}],
          output: [{id:"ndvi", bands:1}, {id:"dataMask", bands:1}]};
}
function evaluatePixel(s) {
  let valid = (s.SCL != 3 && s.SCL != 8 && s.SCL != 9 && s.SCL != 10) ? 1 : 0;
  let ndvi = (s.B08 + s.B04) == 0 ? 0 : (s.B08 - s.B04) / (s.B08 + s.B04);
  return {ndvi: [ndvi], dataMask: [s.dataMask * valid]};
}
""".strip()
        res = SentinelHubStatisticsClient.resolution_for_bbox(bbox)
        return {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
                },
                "data": [{"type": "sentinel-2-l2a"}],
            },
            "aggregation": {
                "timeRange": {"from": f"{date_from}T00:00:00Z", "to": f"{date_to}T23:59:59Z"},
                "aggregationInterval": {"of": "P5D"},
                "evalscript": evalscript,
                "resx": res,
                "resy": res,
            },
            "calculations": {"ndvi": {"statistics": {"default": {"percentiles": {"k": [10, 50, 90]}}}}},
        }
