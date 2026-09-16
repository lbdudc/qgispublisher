"""Unit tests for core.chart_builder — runnable outside QGIS:

    python -m unittest discover -s tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import chart_builder  # noqa: E402


class BuildChartSpecTests(unittest.TestCase):
    def test_bar_chart_has_concrete_tsv_url(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "municipios", "http://localhost:8080", "nombre", "poblacion"
        )
        url = spec["data"][0]["url"]
        self.assertEqual(url, "http://localhost:8080/api/entities/municipioss/export/tsv")
        self.assertNotIn("__", json.dumps(spec))  # no leftover placeholders
        self.assertIn("$schema", spec)

    def test_all_chart_types_build_without_error(self):
        for chart_type in chart_builder.CHART_TYPE_LABELS:
            needs_x, needs_y, needs_color = chart_builder.CHART_TYPE_FIELD_REQUIREMENTS[chart_type]
            spec = chart_builder.build_chart_spec(
                chart_type,
                "layer",
                "http://localhost:8080",
                "category" if needs_x else None,
                "value" if needs_y else None,
                "group" if needs_color else None,
            )
            self.assertIn("marks", spec)
            self.assertIn("data", spec)

    def test_attribute_names_are_mapped(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "layer", "http://localhost:8080", "ID", "Poblacion"
        )
        spec_text = json.dumps(spec)
        self.assertIn('"id2"', spec_text)
        self.assertIn('"poblacion"', spec_text)

    def test_inline_preview_spec_swaps_url_for_values(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "layer", "http://localhost:8080", "cat", "val"
        )
        rows = [{"cat": "a", "val": 1}, {"cat": "b", "val": 2}]
        preview = chart_builder.inline_preview_spec(spec, rows)
        self.assertNotIn("url", preview["data"][0])
        self.assertEqual(preview["data"][0]["values"], rows)
        # Original spec is untouched.
        self.assertIn("url", spec["data"][0])


class ValidateChartSpecTests(unittest.TestCase):
    def test_valid_spec_has_no_issues(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "municipios", "http://localhost:8080", "nombre", "poblacion"
        )
        issues = chart_builder.validate_chart_spec(
            json.dumps(spec),
            ["municipios"],
            {"municipios": {"nombre", "poblacion"}},
        )
        self.assertEqual(issues, [])

    def test_invalid_json_is_flagged(self):
        issues = chart_builder.validate_chart_spec("{not json", [], None)
        self.assertEqual(len(issues), 1)
        self.assertIn("Not valid JSON", issues[0])

    def test_missing_schema_is_flagged(self):
        issues = chart_builder.validate_chart_spec(json.dumps({"data": []}), [], None)
        self.assertTrue(any("schema" in i.lower() for i in issues))

    def test_placeholder_tokens_are_flagged(self):
        spec_text = json.dumps({
            "$schema": chart_builder.VEGA_SCHEMA,
            "data": [{"name": "dataset", "url": "http://x/api/entities/foos/export/tsv"}],
            "marks": [{"encode": {"update": {"x": {"field": "__XFIELD__"}}}}],
        })
        issues = chart_builder.validate_chart_spec(spec_text, [], None)
        self.assertTrue(any("__" in i or "placeholder" in i.lower() for i in issues))

    def test_entity_mismatch_is_flagged(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "wrong_layer", "http://localhost:8080", "x", "y"
        )
        issues = chart_builder.validate_chart_spec(json.dumps(spec), ["municipios"], None)
        self.assertTrue(any("doesn't match any selected layer" in i for i in issues))

    def test_unknown_field_is_flagged(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "municipios", "http://localhost:8080", "nonexistent_field", "poblacion"
        )
        issues = chart_builder.validate_chart_spec(
            json.dumps(spec),
            ["municipios"],
            {"municipios": {"poblacion"}},  # nonexistent_field isn't in here
        )
        self.assertTrue(any("nonexistent_field" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
