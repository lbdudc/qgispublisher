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


if __name__ == "__main__":
    unittest.main()
