"""Weather/rainfall context connectors. Two independent sources on purpose --
ERA5-Land for temperature/soil-moisture-adjacent reanalysis context, CHIRPS
for rainfall specifically (better suited to the East African / rainfed
calendar cards, §21-24 of the prior R&D). Both are queried through GEE by
default since it already hosts harmonized versions of each."""

from .earth_engine import EarthEngineConnector, EarthEngineNotConfigured


class WeatherContextClient:
    def __init__(self, ee_connector: EarthEngineConnector):
        self.ee = ee_connector

    def rainfall_mm(self, geojson_geometry: dict, date_from: str, date_to: str) -> dict:
        """CHIRPS daily rainfall, summed over the window, mean over the AOI."""
        self.ee._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)
        coll = (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterBounds(aoi)
            .filterDate(date_from, date_to)
        )
        total = coll.sum()
        stats = total.reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, scale=5000, maxPixels=1e9)
        return stats.getInfo()

    def soil_moisture_and_temperature(self, geojson_geometry: dict, date_from: str, date_to: str) -> dict:
        """ERA5-Land: volumetric soil water layer 1 + 2m air temperature, mean over window."""
        self.ee._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)
        coll = (
            ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR")
            .filterBounds(aoi)
            .filterDate(date_from, date_to)
            .select(["volumetric_soil_water_layer_1", "temperature_2m"])
        )
        stats = coll.mean().reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, scale=11132, maxPixels=1e9)
        return stats.getInfo()
