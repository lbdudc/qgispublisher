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

    def test_histogram_bin_has_an_extent(self):
        # Vega's bin transform has no default extent; without it the chart fails to render.
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_HISTOGRAM, "layer", "/backend", "value"
        )
        transforms = spec["data"][0]["transform"]
        self.assertEqual(transforms[0]["type"], "extent")
        bin_transform = next(t for t in transforms if t["type"] == "bin")
        self.assertEqual(bin_transform["extent"], {"signal": transforms[0]["signal"]})

    def test_attribute_names_are_mapped(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "layer", "http://localhost:8080", "ID", "Poblacion"
        )
        spec_text = json.dumps(spec)
        self.assertIn('"id2"', spec_text)
        self.assertIn('"poblacion"', spec_text)

    def test_underscored_fields_use_the_generated_camel_case_property(self):
        # The generated app exposes obs_date as obsDate (dsl-util.js lowerCamelCase).
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "layer", "/backend", "obs_date", "area_km2"
        )
        spec_text = json.dumps(spec)
        self.assertIn('"obsDate"', spec_text)
        self.assertIn('"areaKm2"', spec_text)
        self.assertNotIn("obs_date", spec_text)

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

    def test_heatmap_requires_color(self):
        with self.assertRaises(ValueError):
            chart_builder.build_chart_spec(
                chart_builder.CHART_TYPE_HEATMAP, "layer", "http://localhost:8080", "x", "y"
            )

    def test_grouped_bar_requires_color(self):
        with self.assertRaises(ValueError):
            chart_builder.build_chart_spec(
                chart_builder.CHART_TYPE_GROUPED_BAR, "layer", "http://localhost:8080", "x", "y"
            )

    def test_stacked_bar_requires_color(self):
        with self.assertRaises(ValueError):
            chart_builder.build_chart_spec(
                chart_builder.CHART_TYPE_STACKED_BAR, "layer", "http://localhost:8080", "x", "y"
            )

    def test_heatmap_measure_is_color_not_y(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_HEATMAP, "layer", "http://localhost:8080", "x", "y", "measure"
        )
        transform = spec["data"][0]["transform"][0]
        self.assertEqual(transform["fields"], ["measure"])

    def test_bar_without_color_uses_flat_fill(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "layer", "http://localhost:8080", "x", "y"
        )
        fill = spec["marks"][0]["encode"]["update"]["fill"]
        self.assertEqual(fill, {"value": "steelblue"})
        self.assertNotIn("legends", spec)

    def test_bar_with_color_gets_color_scale_and_legend(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "layer", "http://localhost:8080", "x", "y", "group"
        )
        fill = spec["marks"][0]["encode"]["update"]["fill"]
        self.assertEqual(fill, {"scale": "color", "field": "group"})
        self.assertIn("legends", spec)
        color_scale = next(s for s in spec["scales"] if s["name"] == "color")
        self.assertEqual(color_scale["domain"]["field"], "group")

    def test_line_without_color_is_single_series(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_LINE, "layer", "http://localhost:8080", "x", "y"
        )
        self.assertEqual(spec["marks"][0]["type"], "line")
        self.assertNotIn("legends", spec)

    def test_line_with_color_facets_into_series(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_LINE, "layer", "http://localhost:8080", "x", "y", "region"
        )
        group_mark = spec["marks"][0]
        self.assertEqual(group_mark["type"], "group")
        self.assertEqual(group_mark["from"]["facet"]["groupby"], ["region"])
        nested_types = {m["type"] for m in group_mark["marks"]}
        self.assertEqual(nested_types, {"line", "symbol"})
        self.assertIn("legends", spec)

    def test_area_with_color_facets_into_series(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_AREA, "layer", "http://localhost:8080", "x", "y", "region"
        )
        group_mark = spec["marks"][0]
        self.assertEqual(group_mark["type"], "group")
        self.assertEqual(group_mark["from"]["facet"]["groupby"], ["region"])

    def test_scatter_defaults_to_linear_axes(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_SCATTER, "layer", "http://localhost:8080", "x", "y"
        )
        scales = {s["name"]: s for s in spec["scales"]}
        self.assertEqual(scales["x"]["type"], "linear")
        self.assertEqual(scales["y"]["type"], "linear")

    def test_scatter_uses_point_scale_for_categorical_field(self):
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_SCATTER, "layer", "http://localhost:8080", "category", "value",
            field_types={"category": "categorical", "value": "numeric"},
        )
        scales = {s["name"]: s for s in spec["scales"]}
        self.assertEqual(scales["x"]["type"], "point")
        self.assertEqual(scales["y"]["type"], "linear")


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
        # "bogus" is <=10 chars and already a valid DSL identifier, so
        # naming.attribute_name leaves it unchanged and it's easy to assert on.
        spec = chart_builder.build_chart_spec(
            chart_builder.CHART_TYPE_BAR, "municipios", "http://localhost:8080", "bogus", "poblacion"
        )
        issues = chart_builder.validate_chart_spec(
            json.dumps(spec),
            ["municipios"],
            {"municipios": {"poblacion"}},  # bogus isn't in here
        )
        self.assertTrue(any("bogus" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
