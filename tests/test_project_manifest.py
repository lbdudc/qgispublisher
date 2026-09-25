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

    def test_field_info_carries_more_than_the_alias(self):
        descriptor = _vector_descriptor()
        descriptor = layer_export.LayerDescriptor(**{
            **descriptor.__dict__,
            "field_info": {
                "nom": {"alias": "Name"},
                "code": {"hidden": True, "valueMap": {"1": "Urban"}},
                "empty": {},
            },
        })
        entry = project_manifest.build_layer_entry(descriptor, "roads")
        self.assertEqual(
            entry["fields"],
            [
                {"name": "nom", "alias": "Name"},
                {"name": "code", "hidden": True, "valueMap": {"1": "Urban"}},
            ],
        )

    def test_raster_descriptor_works_the_same_way(self):
        entry = project_manifest.build_layer_entry(_raster_descriptor(), "ortho")
        self.assertEqual(entry["staged"], "ortho")
        self.assertEqual(entry["title"], "Ortho")
        self.assertNotIn("fields", entry)


class DisplayFieldTests(unittest.TestCase):
    FIELDS = ["fid", "nombre", 'weird "name"']

    def test_a_plain_field_reference_is_the_display_field(self):
        f = layer_export.display_field_from_expression
        self.assertEqual(f('"nombre"', self.FIELDS), "nombre")
        self.assertEqual(f("  nombre ", self.FIELDS), "nombre")
        self.assertEqual(f('"weird ""name"""', self.FIELDS), 'weird "name"')

    def test_real_expressions_and_unknown_fields_are_not(self):
        f = layer_export.display_field_from_expression
        for expression in ('"nombre" || ' ' || "fid"', "upper(nombre)", '"nope"', "", None):
            self.assertEqual(f(expression, self.FIELDS), "", expression)

    def test_the_manifest_entry_carries_it(self):
        descriptor = layer_export.LayerDescriptor(
            layer_id="id1", name="Roads", source="/data/roads.shp", crs_authid="EPSG:4326",
            feature_count=1, field_names=("nombre",), display_field="nombre",
        )
        self.assertEqual(project_manifest.build_layer_entry(descriptor, "roads")["displayField"], "nombre")
        self.assertNotIn("displayField", project_manifest.build_layer_entry(_vector_descriptor(), "roads"))


class RemapFieldKeysTests(unittest.TestCase):
    def test_values_are_kept_and_keys_follow_the_rename(self):
        info = {"1er Apelli": {"alias": "Primer apellido", "hidden": True}, "nombre": {}}
        rename_map = {"1er Apelli": "f1erApelli"}
        self.assertEqual(
            project_manifest.remap_field_keys(info, rename_map),
            {"f1erApelli": {"alias": "Primer apellido", "hidden": True}, "nombre": {}},
        )

    def test_empty_rename_map_is_noop(self):
        info = {"a": {"alias": "A"}}
        self.assertEqual(project_manifest.remap_field_keys(info, {}), info)


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

    def test_group_dir_by_name_written_inverted(self):
        manifest = project_manifest.build_manifest(
            {}, [], group_dir_by_name={"Salud Pública": "Salud_Publica", "Administrativo": "Administrativo"}
        )
        self.assertEqual(
            manifest["groups"],
            {"Salud_Publica": "Salud Pública", "Administrativo": "Administrativo"},
        )

    def test_no_groups_key_when_nothing_grouped(self):
        manifest = project_manifest.build_manifest({}, [])
        self.assertNotIn("groups", manifest)
        manifest = project_manifest.build_manifest({}, [], group_dir_by_name={})
        self.assertNotIn("groups", manifest)

    def test_integrates_with_build_layer_entry(self):
        entries = [
            project_manifest.build_layer_entry(_vector_descriptor(), "roads", {"order": 0, "visible": True}),
            project_manifest.build_layer_entry(_raster_descriptor(), "ortho", {"order": 1, "visible": False}),
        ]
        manifest = project_manifest.build_manifest({"title": "Demo"}, entries)
        self.assertEqual(len(manifest["layers"]), 2)
        self.assertEqual(manifest["layers"][0]["staged"], "roads")
        self.assertEqual(manifest["layers"][1]["visible"], False)


class BookmarkAndCrsTests(unittest.TestCase):
    def test_bookmarks_keep_named_reprojected_extents(self):
        extent = {"crs": "EPSG:4326", "xmin": -9.0, "ymin": 42.0, "xmax": -7.0, "ymax": 43.5}
        result = project_manifest.build_bookmark_entries([("  A Coruna ", extent)])
        self.assertEqual(
            result,
            [{"name": "A Coruna", "xmin": -9.0, "ymin": 42.0, "xmax": -7.0, "ymax": 43.5}],
        )

    def test_bookmarks_drop_unnamed_or_unprojectable(self):
        extent = {"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1}
        self.assertEqual(
            project_manifest.build_bookmark_entries([("", extent), ("x", None), (None, extent)]),
            [],
        )

    def test_crs_info(self):
        self.assertEqual(
            project_manifest.build_crs_info("EPSG:25829", False, "+proj=utm +zone=29"),
            {"authid": "EPSG:25829", "isGeographic": False, "proj4": "+proj=utm +zone=29"},
        )
        self.assertEqual(
            project_manifest.build_crs_info("EPSG:4326", True),
            {"authid": "EPSG:4326", "isGeographic": True},
        )

    def test_crs_info_without_authid_is_none(self):
        self.assertIsNone(project_manifest.build_crs_info("", False, "+proj=x"))


class GroupPathTests(unittest.TestCase):
    def test_top_level_group_is_just_its_name(self):
        self.assertEqual(project_manifest.join_group_path(None, "Roads"), "Roads")

    def test_nested_group_keeps_the_full_path(self):
        self.assertEqual(project_manifest.join_group_path("Admin", "Roads"), "Admin / Roads")
        self.assertEqual(
            project_manifest.join_group_path(project_manifest.join_group_path("A", "B"), "C"), "A / B / C"
        )

    def test_same_named_subgroups_get_different_folders(self):
        from core import naming

        dirs = naming.assign_group_dirnames(["Admin / Roads", "Water / Roads"])
        self.assertEqual(len(set(dirs.values())), 2)

    def test_a_group_named_branding_does_not_take_the_logo_folder(self):
        from core import naming

        self.assertNotEqual(naming.assign_group_dirnames(["Branding"])["Branding"].lower(), "branding")


if __name__ == "__main__":
    unittest.main()
