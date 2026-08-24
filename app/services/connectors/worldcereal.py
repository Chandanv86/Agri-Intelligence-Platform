"""WorldCereal crop-type mask -- the global fallback (and for 5 of 6 countries,
the PRIMARY) crop-area source, since AMED only covers India. Served via GEE's
ESA WorldCereal 2021 product as the accessible path; the WorldCereal project's
own RDM/API can be swapped in later without changing this seam's interface."""


class WorldCerealClient:
    def __init__(self, ee_connector):
        self.ee = ee_connector

    def crop_extent(self, geojson_geometry: dict, crop_class: str = "temporarycrops") -> dict:
        self.ee._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)
        # 'temporarycrops', 'maize', 'wintercereals', 'springcereals', 'irrigation'
        # are PRODUCTS in this collection, selected via the 'product' property --
        # they are NOT band names. Every image exposes the same two bands,
        # 'classification' (0 = not this class, 100 = this class) and
        # 'confidence', so selecting the product as a band fails with
        # "Band pattern 'temporarycrops' did not match any bands".
        coll = (
            ee.ImageCollection("ESA/WorldCereal/2021/MARKERS/v100")
            .filterBounds(aoi)
        )
        filtered = coll.filter(ee.Filter.eq("product", crop_class))
        # Collection vintages disagree on how the product is exposed: in some it
        # is a 'product' property, in others the collection is already a single
        # product. Filtering on a property that doesn't exist yields an EMPTY
        # collection, and mosaicking that gives an image with NO bands ("Band
        # pattern 'classification' was applied to an Image with no bands").
        # So fall back to the unfiltered mosaic, server-side, in one round trip.
        chosen = ee.ImageCollection(
            ee.Algorithms.If(filtered.size().gt(0), filtered, coll)
        )
        img = chosen.mosaic().select("classification")
        stats = img.reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, scale=10, maxPixels=1e9)
        return stats.getInfo()

    def describe(self, geojson_geometry: dict) -> dict:
        """Diagnostic: what this collection actually exposes over an AOI --
        image count, band names, and the first image's properties. Use this
        instead of guessing at band/property names."""
        self.ee._ensure_initialized()
        import ee

        aoi = ee.Geometry(geojson_geometry)
        coll = ee.ImageCollection("ESA/WorldCereal/2021/MARKERS/v100").filterBounds(aoi)
        first = ee.Image(coll.first())
        return {
            "image_count": coll.size().getInfo(),
            "mosaic_bands": coll.mosaic().bandNames().getInfo(),
            "first_bands": first.bandNames().getInfo(),
            "first_properties": first.toDictionary().getInfo(),
        }
