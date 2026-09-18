"""Unit tests for core.naming — runnable outside QGIS with plain unittest:

    python -m unittest discover -s tests

These assert the Python port matches the JS helpers it mirrors
(@lbdudc/gis-publisher's str-util.js, dsl-util.js and spl-js-engine's normalize()),
so a plugin-built entity/URL/attribute name always agrees with what the generator
actually derives.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import naming  # noqa: E402


class NamingTests(unittest.TestCase):
    def test_lower_camel_case_underscores(self):
        self.assertEqual(naming.lower_camel_case("unemployment_by_district"), "unemploymentByDistrict")

    def test_upper_camel_case_underscores(self):
        self.assertEqual(naming.upper_camel_case("unemployment_by_district"), "UnemploymentByDistrict")

    def test_camel_case_mixed_separators(self):
        self.assertEqual(naming.upper_camel_case("my-layer name"), "MyLayerName")

    def test_camel_case_already_camel(self):
        self.assertEqual(naming.upper_camel_case("Municipios"), "Municipios")

    def test_entity_name(self):
        self.assertEqual(naming.entity_name("municipios"), "Municipios")

    def test_entity_url_segment_appends_s(self):
        self.assertEqual(naming.entity_url_segment("municipios"), "municipioss")
        self.assertEqual(naming.entity_url_segment("unemployment_by_district"), "unemploymentByDistricts")

    def test_attribute_name_lowercases(self):
        self.assertEqual(naming.attribute_name("Nombre"), "nombre")

    def test_attribute_name_id_becomes_id2(self):
        self.assertEqual(naming.attribute_name("id"), "id2")
        self.assertEqual(naming.attribute_name("ID"), "id2")

    def test_empty_string(self):
        self.assertEqual(naming.upper_camel_case(""), "")
        self.assertEqual(naming.entity_url_segment(""), "")

    def test_starts_with_digit(self):
        self.assertTrue(naming.starts_with_digit("0_wells"))
        self.assertFalse(naming.starts_with_digit("wells"))

    def test_safe_field_name_leaves_valid_names_untouched(self):
        self.assertEqual(naming.safe_field_name("Nombre"), "Nombre")
        self.assertEqual(naming.safe_field_name("descriptio"), "descriptio")

    def test_safe_field_name_fixes_leading_digit_and_spaces(self):
        # DBF-truncated "1er Apellido" — the exact field that broke the DSL parser.
        self.assertEqual(naming.safe_field_name("1er Apelli"), "f1erApelli")
        self.assertTrue(naming.is_valid_dsl_identifier(naming.safe_field_name("1er Apelli")))
        self.assertLessEqual(len(naming.safe_field_name("1er Apelli")), 10)

    def test_safe_field_name_strips_accents_and_punctuation(self):
        result = naming.safe_field_name("2º Apelli")
        self.assertTrue(naming.is_valid_dsl_identifier(result))

    def test_attribute_name_matches_safe_field_name_pipeline(self):
        # attribute_name must reflect the same rename the runner stages, since the
        # CLI derives the entity attribute from whatever field name it actually reads.
        self.assertEqual(naming.attribute_name("1er Apelli"), naming.safe_field_name("1er Apelli").lower())

    def test_rename_map_only_includes_changed_fields(self):
        fields = ["fid", "Name", "1er Apelli", "descriptio"]
        renamed = naming.rename_map_for_fields(fields)
        self.assertEqual(set(renamed.keys()), {"1er Apelli"})
        self.assertEqual(renamed["1er Apelli"], "f1erApelli")

    def test_rename_map_deduplicates_collisions(self):
        fields = ["1a", "-1a"]
        renamed = naming.rename_map_for_fields(fields)
        self.assertEqual(len(renamed), 2)
        self.assertNotEqual(renamed["1a"], renamed["-1a"])

    def test_suggest_app_name_leaves_valid_names_untouched_semantically(self):
        self.assertTrue(naming.is_valid_dsl_identifier(naming.suggest_app_name("MyApp")))

    def test_suggest_app_name_fixes_spaces_and_punctuation(self):
        # A QGIS project title is a realistic input: spaces, punctuation, mixed case.
        result = naming.suggest_app_name("Health Centers - A Coruña (2024)")
        self.assertTrue(naming.is_valid_dsl_identifier(result))

    def test_suggest_app_name_fixes_leading_digit(self):
        result = naming.suggest_app_name("2024 Census")
        self.assertTrue(naming.is_valid_dsl_identifier(result))

    def test_suggest_app_name_empty_input(self):
        self.assertTrue(naming.is_valid_dsl_identifier(naming.suggest_app_name("")))
        self.assertTrue(naming.is_valid_dsl_identifier(naming.suggest_app_name("   ")))
        self.assertTrue(naming.is_valid_dsl_identifier(naming.suggest_app_name("---")))

    def test_layer_source_basename_from_path(self):
        class FakeLayer:
            def source(self):
                return "/data/municipios.shp|layername=municipios"

            def name(self):
                return "Municipios (renamed)"

        self.assertEqual(naming.layer_source_basename(FakeLayer()), "municipios")

    def test_layer_source_basename_falls_back_to_name(self):
        class FakeLayer:
            def source(self):
                raise RuntimeError("no source")

            def name(self):
                return "fallback name"

        self.assertEqual(naming.layer_source_basename(FakeLayer()), "fallback name")

    def test_layer_source_basename_prefers_layername_over_container_file(self):
        # Two GeoPackage layers from the same .gpkg must not both propose "data".
        class FakeLayer:
            def source(self):
                return "/data/data.gpkg|layername=roads"

            def name(self):
                return "Roads"

        self.assertEqual(naming.layer_source_basename(FakeLayer()), "roads")

    def test_safe_field_name_truncates_overlong_valid_identifier(self):
        # Valid per is_valid_dsl_identifier but too long for a DBF field slot — only
        # reachable via a non-shapefile source (GeoPackage/PostGIS have no 10-char cap).
        result = naming.safe_field_name("descriptionLong")
        self.assertTrue(naming.is_valid_dsl_identifier(result))
        self.assertLessEqual(len(result), 10)
        self.assertNotEqual(result, "descriptionLong")

    def test_rename_map_includes_overlong_valid_identifiers(self):
        fields = ["descriptionLong", "name"]
        renamed = naming.rename_map_for_fields(fields)
        self.assertIn("descriptionLong", renamed)
        self.assertNotIn("name", renamed)

    def test_staged_basename_no_collision(self):
        self.assertEqual(naming.staged_basename("roads", set()), "roads")

    def test_staged_basename_dedupes_case_insensitively(self):
        self.assertEqual(naming.staged_basename("Roads", {"roads"}), "Roads_2")
        self.assertEqual(naming.staged_basename("roads", {"roads", "roads_2"}), "roads_3")

    def test_assign_staged_basenames_dedupes_in_order(self):
        result = naming.assign_staged_basenames([
            ("a", "data"), ("b", "data"), ("c", "roads"),
        ])
        self.assertEqual(result, {"a": "data", "b": "data_2", "c": "roads"})


if __name__ == "__main__":
    unittest.main()
