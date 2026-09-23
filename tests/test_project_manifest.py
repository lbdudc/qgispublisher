"""Unit tests for core.project_manifest's pure half — runnable outside QGIS:

    python -m unittest discover -s tests

Covers build_manifest and build_layer_entry only; describe_project,
layers_extent_wgs84 and describe_layer_tree are QGIS-touching adapters
exercised manually (see the plan's Verification section), matching the
pure/adapter split used by the other test modules here.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layer_export, project_manifest  # noqa: E402


def _vector_descriptor(name="Roads", opacity=1.0, scale_visibility=False,
                        min_scale=0.0, max_scale=0.0, field_aliases=None):
    return layer_export.LayerDescriptor(
        layer_id="id1",
        name=name,
        source="/data/roads.shp",
        crs_authid="EPSG:4326",
        feature_count=10,
        field_names=("name", "length"),
        opacity=opacity,
        scale_visibility=scale_visibility,
        min_scale=min_scale,
        max_scale=max_scale,
        field_aliases=field_aliases or {},
    )


def _raster_descriptor(name="Ortho", opacity=1.0, scale_visibility=False,
                        min_scale=0.0, max_scale=0.0):
    return layer_export.RasterDescriptor(
        layer_id="id2",
        name=name,
        source="/data/ortho.tif",
        provider_type="gdal",
        opacity=opacity,
        scale_visibility=scale_visibility,
        min_scale=min_scale,
        max_scale=max_scale,
    )


class BuildLayerEntryTests(unittest.TestCase):
    def test_minimal_vector_entry(self):
        entry = project_manifest.build_layer_entry(_vector_descriptor(), "roads")
        self.assertEqual(entry["staged"], "roads")
        self.assertEqual(entry["title"], "Roads")
        self.assertEqual(entry["opacity"], 1.0)
        # No tree_entry given -> visible/order/group simply absent, not None.
        self.assertNotIn("visible", entry)
        self.assertNotIn("order", entry)
        self.assertNotIn("group", entry)
        # No scale-based visibility -> minScale/maxScale absent too.
        self.assertNotIn("minScale", entry)
        self.assertNotIn("maxScale", entry)
        self.assertNotIn("fields", entry)

    def test_tree_entry_is_merged_in(self):
        tree_entry = {"order": 3, "visible": False, "group": "Administrative"}
        entry = project_manifest.build_layer_entry(_vector_descriptor(), "roads", tree_entry)
        self.assertEqual(entry["order"], 3)
        self.assertEqual(entry["visible"], False)
        self.assertEqual(entry["group"], "Administrative")

    def test_scale_visibility_includes_min_max(self):
        descriptor = _vector_descriptor(scale_visibility=True, min_scale=1000.0, max_scale=50000.0)
        entry = project_manifest.build_layer_entry(descriptor, "roads")
        self.assertEqual(entry["minScale"], 1000.0)
        self.assertEqual(entry["maxScale"], 50000.0)

    def test_scale_visibility_off_omits_min_max_even_if_nonzero(self):
        # A layer that HAD scale limits set once but toggled the checkbox off
        # shouldn't have stale min/maxScale resurrected into the manifest.
        descriptor = _vector_descriptor(scale_visibility=False, min_scale=1000.0, max_scale=50000.0)
        entry = project_manifest.build_layer_entry(descriptor, "roads")
        self.assertNotIn("minScale", entry)
        self.assertNotIn("maxScale", entry)

    def test_field_aliases_become_fields_list(self):
        descriptor = _vector_descriptor(field_aliases={"nom": "Name", "pob": "Population"})
        entry = project_manifest.build_layer_entry(descriptor, "roads")
        self.assertEqual(
            entry["fields"],
            [{"name": "nom", "alias": "Name"}, {"name": "pob", "alias": "Population"}],
        )

    def test_raster_descriptor_works_the_same_way(self):
        entry = project_manifest.build_layer_entry(_raster_descriptor(), "ortho")
        self.assertEqual(entry["staged"], "ortho")
        self.assertEqual(entry["title"], "Ortho")
        self.assertNotIn("fields", entry)


class RemapFieldAliasesTests(unittest.TestCase):
    def test_empty_rename_map_is_noop(self):
        aliases = {"nombre": "Nombre"}
        self.assertEqual(project_manifest.remap_field_aliases(aliases, {}), aliases)

    def test_renamed_field_key_follows_the_rename(self):
        aliases = {"1er Apelli": "Primer apellido"}
        rename_map = {"1er Apelli": "f1erApelli"}
        self.assertEqual(
            project_manifest.remap_field_aliases(aliases, rename_map),
            {"f1erApelli": "Primer apellido"},
        )

    def test_field_not_in_rename_map_keeps_its_name(self):
        aliases = {"nombre": "Nombre", "1er Apelli": "Primer apellido"}
        rename_map = {"1er Apelli": "f1erApelli"}
        self.assertEqual(
            project_manifest.remap_field_aliases(aliases, rename_map),
            {"nombre": "Nombre", "f1erApelli": "Primer apellido"},
        )


class BuildManifestTests(unittest.TestCase):
    def test_schema_version_and_shape(self):
        manifest = project_manifest.build_manifest({"title": "Demo"}, [])
        self.assertEqual(manifest["schemaVersion"], project_manifest.MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["project"], {"title": "Demo"})
        self.assertEqual(manifest["layers"], [])

    def test_none_project_fields_are_dropped(self):
        manifest = project_manifest.build_manifest({"title": "Demo", "extent": None}, [])
        self.assertEqual(manifest["project"], {"title": "Demo"})

    def test_none_project_info_becomes_empty_dict(self):
        manifest = project_manifest.build_manifest(None, [])
        self.assertEqual(manifest["project"], {})

    def test_none_fields_dropped_from_each_layer_entry(self):
        entries = [{"staged": "roads", "title": "Roads", "order": None, "opacity": 0.5}]
        manifest = project_manifest.build_manifest({}, entries)
        self.assertEqual(manifest["layers"], [{"staged": "roads", "title": "Roads", "opacity": 0.5}])

    def test_preserves_entry_order(self):
        entries = [
            {"staged": "a", "title": "A"},
            {"staged": "b", "title": "B"},
            {"staged": "c", "title": "C"},
        ]
        manifest = project_manifest.build_manifest({}, entries)
        self.assertEqual([e["staged"] for e in manifest["layers"]], ["a", "b", "c"])

    def test_integrates_with_build_layer_entry(self):
        entries = [
            project_manifest.build_layer_entry(_vector_descriptor(), "roads", {"order": 0, "visible": True}),
            project_manifest.build_layer_entry(_raster_descriptor(), "ortho", {"order": 1, "visible": False}),
        ]
        manifest = project_manifest.build_manifest({"title": "Demo"}, entries)
        self.assertEqual(len(manifest["layers"]), 2)
        self.assertEqual(manifest["layers"][0]["staged"], "roads")
        self.assertEqual(manifest["layers"][1]["visible"], False)


if __name__ == "__main__":
    unittest.main()
