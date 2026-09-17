"""Unit tests for core.layer_export's pure planning half — runnable outside QGIS:

    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layer_export  # noqa: E402


def _descriptor(layer_id, name, source="", crs_authid="EPSG:4326", feature_count=1,
                 field_names=(), has_geometry=True):
    return layer_export.LayerDescriptor(
        layer_id=layer_id,
        name=name,
        source=source,
        crs_authid=crs_authid,
        feature_count=feature_count,
        field_names=tuple(field_names),
        has_geometry=has_geometry,
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


if __name__ == "__main__":
    unittest.main()
