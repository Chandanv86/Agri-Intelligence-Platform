"""Google Earth Engine connector seam. §62 of the prior R&D + §124 tech
recommendation. `earthengine-api` is imported lazily so the rest of the app
doesn't hard-depend on it being installed/authenticated -- this keeps DEMO
mode fully runnable with zero GEE setup, per the project's non-negotiable
demo/live separation rule.

No credentials are embedded in this repo. To go LIVE:
  pip install earthengine-api
  set GEE_PROJECT and GEE_SERVICE_ACCOUNT_JSON_PATH in .env
"""


class EarthEngineNotConfigured(RuntimeError):
    pass


class EarthEngineConnector:
    def __init__(self, project: str | None = None, service_account_json_path: str | None = None):
        self.project = project
        self.service_account_json_path = service_account_json_path
        self._initialized = False

    def configured(self) -> bool:
        return bool(self.project)

    def _ensure_initialized(self):
        if self._initialized:
            return
        if not self.configured():
            raise EarthEngineNotConfigured("GEE_PROJECT is not set")
        import ee  # lazy import -- only required in LIVE mode

        if self.service_account_json_path:
            credentials = ee.ServiceAccountCredentials(None, self.service_account_json_path)
            ee.Initialize(credentials, project=self.project)
        else:
            ee.Initialize(project=self.project)
        self._initialized = True

    def ndvi_stats_for_geometry(self, geojson_geometry: dict, date_from: str, date_to: str) -> dict:
        """Returns mean/stdDev NDVI over a geometry using harmonized Sentinel-2
        SR, cloud-masked via the SCL band. Requires GEE credentials -- callers
        must catch EarthEngineNotConfigured and fall back to DEMO data_status."""
        self._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)

        def mask_and_ndvi(img):
            scl = img.select("SCL")
            mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))
            ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
            return ndvi.updateMask(mask)

        coll = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filterDate(date_from, date_to)
            .map(mask_and_ndvi)
        )
        stats = coll.mean().reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
            geometry=aoi,
            scale=10,
            maxPixels=1e9,
        )
        return stats.getInfo()

    def dynamic_world_crop_probability(self, geojson_geometry: dict, date_from: str, date_to: str) -> dict:
        """Dynamic World V1 'crops' class probability, mean over the window.
        10 m near-real-time LULC (Sentinel-2 driven, ~2-3 day typical latency)."""
        self._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)
        coll = (
            ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
            .filterBounds(aoi)
            .filterDate(date_from, date_to)
            .select("crops")
        )
        stats = coll.mean().reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi, scale=10, maxPixels=1e9
        )
        return stats.getInfo()

    def sentinel1_vh_backscatter_stats(self, geojson_geometry: dict, date_from: str, date_to: str) -> dict:
        """Sentinel-1 GRD VH backscatter mean -- radar complement, cloud-independent.
        Useful for establishment detection under persistent cloud cover (§11/§36
        of the prior R&D)."""
        self._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)
        coll = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(aoi)
            .filterDate(date_from, date_to)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
            .select("VH")
        )
        stats = coll.mean().reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
            geometry=aoi,
            scale=10,
            maxPixels=1e9,
        )
        return stats.getInfo()
