"""Unit tests for core.layer_export's pure planning half — runnable outside QGIS:

    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layer_export  # noqa: E402


def _descriptor(layer_id, name, source="", crs_authid="EPSG:4326", feature_count=1,
                 field_names=(), has_geometry=True, renderer_type=""):
    return layer_export.LayerDescriptor(
        layer_id=layer_id,
        name=name,
        source=source,
        crs_authid=crs_authid,
        feature_count=feature_count,
        field_names=tuple(field_names),
        has_geometry=has_geometry,
        renderer_type=renderer_type,
    )


class PlanExportsTests(unittest.TestCase):
    def test_basenames_come_from_source_layername(self):
        descriptors = [
            _descriptor("id1", "Roads", source="/data/data.gpkg|layername=roads"),
            _descriptor("id2", "Parcels", source="/data/data.gpkg|layername=parcels"),
        ]
        plans = layer_export.plan_exports(descriptors)
        basenames = {p.layer_id: p.staged_basename for p in plans}
        self.assertEqual(basenames, {"id1": "roads", "id2": "parcels"})

    def test_colliding_basenames_are_deduplicated(self):
        descriptors = [
            _descriptor("id1", "Data", source="/a/data.gpkg"),
            _descriptor("id2", "Data", source="/b/data.gpkg"),
        ]
        plans = layer_export.plan_exports(descriptors)
        basenames = [p.staged_basename for p in plans]
        self.assertEqual(len(set(basenames)), 2)
        self.assertIn("data", basenames)

    def test_no_crs_is_warned(self):
        plans = layer_export.plan_exports([_descriptor("id1", "x", crs_authid="")])
        self.assertIn(layer_export.WARN_NO_CRS, plans[0].warnings)

    def test_empty_layer_is_warned(self):
        plans = layer_export.plan_exports([_descriptor("id1", "x", feature_count=0)])
        self.assertIn(layer_export.WARN_EMPTY_LAYER, plans[0].warnings)

    def test_no_geometry_is_warned(self):
        plans = layer_export.plan_exports([_descriptor("id1", "x", has_geometry=False)])
        self.assertIn(layer_export.WARN_NO_GEOMETRY, plans[0].warnings)

    def test_too_many_fields_is_warned(self):
        many_fields = [f"f{i}" for i in range(layer_export.MAX_DBF_FIELDS + 1)]
        plans = layer_export.plan_exports([_descriptor("id1", "x", field_names=many_fields)])
        self.assertIn(layer_export.WARN_TOO_MANY_FIELDS, plans[0].warnings)

    def test_needs_reproject_when_crs_differs_from_target(self):
        plans = layer_export.plan_exports(
            [_descriptor("id1", "x", crs_authid="EPSG:25830")],
            target_crs_authid="EPSG:4326",
        )
        self.assertTrue(plans[0].needs_reproject)

    def test_no_reproject_when_crs_matches_target(self):
        plans = layer_export.plan_exports(
            [_descriptor("id1", "x", crs_authid="EPSG:4326")],
            target_crs_authid="EPSG:4326",
        )
        self.assertFalse(plans[0].needs_reproject)

    def test_no_reproject_flagged_when_crs_missing(self):
        # NO_CRS already covers this case; don't also claim a specific reprojection.
        plans = layer_export.plan_exports([_descriptor("id1", "x", crs_authid="")])
        self.assertFalse(plans[0].needs_reproject)

    def test_rename_map_and_warning_for_dbf_unsafe_fields(self):
        plans = layer_export.plan_exports(
            [_descriptor("id1", "x", field_names=["1er Apelli", "name"])]
        )
        self.assertIn("1er Apelli", plans[0].rename_map)
        self.assertIn(layer_export.WARN_RENAMED_FIELDS, plans[0].warnings)

    def test_no_rename_warning_when_all_fields_are_safe(self):
        plans = layer_export.plan_exports([_descriptor("id1", "x", field_names=["name", "pop"])])
        self.assertNotIn(layer_export.WARN_RENAMED_FIELDS, plans[0].warnings)
        self.assertEqual(plans[0].rename_map, {})

    def test_reserved_dsl_keyword_basename_is_warned(self):
        # Stages as "point" -> CREATE ENTITY Point -> collides with the DSL
        # grammar's own TYPE token.
        plans = layer_export.plan_exports([_descriptor("id1", "Point")])
        self.assertIn(layer_export.WARN_RESERVED_ENTITY_NAME, plans[0].warnings)

    def test_ordinary_basename_is_not_warned_as_reserved(self):
        plans = layer_export.plan_exports([_descriptor("id1", "Municipios")])
        self.assertNotIn(layer_export.WARN_RESERVED_ENTITY_NAME, plans[0].warnings)

    def test_unstylable_renderer_is_warned(self):
        # Verified against real QGIS: saveSldStyle() fails outright for these.
        for renderer_type in layer_export.RENDERER_TYPES_UNSTYLABLE:
            plans = layer_export.plan_exports([_descriptor("id1", "x", renderer_type=renderer_type)])
            self.assertIn(layer_export.WARN_UNSTYLABLE_RENDERER, plans[0].warnings, renderer_type)
            self.assertNotIn(layer_export.WARN_DEGRADED_RENDERER, plans[0].warnings, renderer_type)

    def test_degraded_renderer_is_warned(self):
        # Verified against real QGIS: saveSldStyle() "succeeds" but with a
        # generic default style, silently dropping the actual look.
        for renderer_type in layer_export.RENDERER_TYPES_DEGRADED:
            plans = layer_export.plan_exports([_descriptor("id1", "x", renderer_type=renderer_type)])
            self.assertIn(layer_export.WARN_DEGRADED_RENDERER, plans[0].warnings, renderer_type)
            self.assertNotIn(layer_export.WARN_UNSTYLABLE_RENDERER, plans[0].warnings, renderer_type)

    def test_faithful_renderer_types_are_not_warned(self):
        for renderer_type in ("singleSymbol", "categorizedSymbol", "graduatedSymbol", "RuleRenderer"):
            plans = layer_export.plan_exports([_descriptor("id1", "x", renderer_type=renderer_type)])
            self.assertNotIn(layer_export.WARN_UNSTYLABLE_RENDERER, plans[0].warnings, renderer_type)
            self.assertNotIn(layer_export.WARN_DEGRADED_RENDERER, plans[0].warnings, renderer_type)

    def test_sld_rename_map_covers_case_only_differences_dbf_rename_map_skips(self):
        # "TOTAL" is a valid, short DBF field name, so rename_map (DBF-safety only)
        # leaves it alone — but dsl-util.js lowercases every field unconditionally
        # when deriving the generated app's column name, so the SLD rewrite map must
        # catch this even though the DBF rename map doesn't.
        plans = layer_export.plan_exports(
            [_descriptor("id1", "x", field_names=["TOTAL", "pop"])]
        )
        self.assertNotIn("TOTAL", plans[0].rename_map)
        self.assertEqual(plans[0].sld_rename_map, {"TOTAL": "total"})

    def test_sld_rename_map_empty_when_all_fields_already_lowercase(self):
        plans = layer_export.plan_exports([_descriptor("id1", "x", field_names=["name", "pop"])])
        self.assertEqual(plans[0].sld_rename_map, {})

    def test_basename_by_id_override_is_used_verbatim(self):
        # A raster staged alongside these vectors would otherwise never collide-check
        # against them — passing a precomputed basename_by_id is how the runner
        # shares one namespace across both. plan_exports must honour it rather than
        # recomputing from descriptors alone.
        descriptors = [_descriptor("id1", "Roads", source="/data/roads.shp")]
        plans = layer_export.plan_exports(descriptors, basename_by_id={"id1": "roads_2"})
        self.assertEqual(plans[0].staged_basename, "roads_2")


def _raster_descriptor(layer_id, name, source, provider_type):
    return layer_export.RasterDescriptor(
        layer_id=layer_id, name=name, source=source, provider_type=provider_type
    )


class ClassifyRasterTests(unittest.TestCase):
    def test_gdal_provider_is_local(self):
        plan = layer_export.classify_raster(
            _raster_descriptor("id1", "elevation", "/data/elevation.tif", "gdal")
        )
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_LOCAL)

    def test_wms_with_layers_param_is_scoped(self):
        source = "crs=EPSG:4326&format=image/png&layers=roads&styles=default&url=https://example.com/wms"
        plan = layer_export.classify_raster(_raster_descriptor("id1", "Roads WMS", source, "wms"))
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_WMS)
        self.assertEqual(plan.wms_request["url"], "https://example.com/wms")
        self.assertEqual(plan.wms_request["layers"], ["roads"])
        self.assertEqual(plan.wms_request["styles"], ["default"])
        self.assertEqual(plan.wms_request["crs"], "EPSG:4326")
        self.assertEqual(plan.wms_request["format"], "image/png")
        self.assertEqual(plan.message, "")

    def test_wms_layers_param_can_list_multiple_sublayers(self):
        source = "layers=roads,parcels&url=https://example.com/wms"
        plan = layer_export.classify_raster(_raster_descriptor("id1", "x", source, "wms"))
        self.assertEqual(plan.wms_request["layers"], ["roads", "parcels"])

    def test_wms_without_layers_param_is_flagged_but_kept(self):
        source = "url=https://example.com/wms"
        plan = layer_export.classify_raster(_raster_descriptor("id1", "x", source, "wms"))
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_WMS)
        self.assertEqual(plan.wms_request["layers"], [])
        self.assertIn("entire remote service", plan.message)

    def test_wms_without_url_is_rejected(self):
        plan = layer_export.classify_raster(_raster_descriptor("id1", "x", "layers=roads", "wms"))
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_REJECTED)

    def test_xyz_tile_layer_is_rejected(self):
        source = "type=xyz&url=https://tile.example.com/{z}/{x}/{y}.png"
        plan = layer_export.classify_raster(_raster_descriptor("id1", "Basemap", source, "wms"))
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_REJECTED)
        self.assertIn("XYZ", plan.message)

    def test_arcgis_provider_is_rejected(self):
        plan = layer_export.classify_raster(
            _raster_descriptor("id1", "x", "url=https://example.com/rest", "arcgismapserver")
        )
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_REJECTED)

    def test_unrecognized_provider_is_rejected_with_provider_named_in_message(self):
        plan = layer_export.classify_raster(_raster_descriptor("id1", "x", "", "wcs"))
        self.assertEqual(plan.kind, layer_export.RASTER_KIND_REJECTED)
        self.assertIn("wcs", plan.message)

    def test_url_percent_encoding_is_decoded(self):
        source = "layers=roads&url=https%3A%2F%2Fexample.com%2Fwms%3Fservice%3DWMS"
        plan = layer_export.classify_raster(_raster_descriptor("id1", "x", source, "wms"))
        self.assertEqual(plan.wms_request["url"], "https://example.com/wms?service=WMS")


if __name__ == "__main__":
    unittest.main()
