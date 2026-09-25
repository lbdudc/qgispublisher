"""Unit tests for core.popup (pure, runnable outside QGIS)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import popup  # noqa: E402

FIELDS = ["nombre", "poblacion", 'odd "name"']


class ConvertMapTipTests(unittest.TestCase):
    def test_empty_is_no_template_and_no_problem(self):
        self.assertEqual(popup.convert_map_tip("", FIELDS), (None, None))
        self.assertEqual(popup.convert_map_tip("  \n ", FIELDS), (None, None))
        self.assertEqual(popup.convert_map_tip(None, FIELDS), (None, None))

    def test_field_references_become_placeholders(self):
        html = '<b>[% "nombre" %]</b><br>Pop: [%poblacion%] / [% nombre %] / [% "odd ""name""" %]'
        template, problem = popup.convert_map_tip(html, FIELDS)
        self.assertIsNone(problem)
        self.assertEqual(template, "<b>{{nombre}}</b><br>Pop: {{poblacion}} / {{nombre}} / {{odd \"name\"}}")

    def test_text_without_expressions_is_kept_as_it_is(self):
        self.assertEqual(popup.convert_map_tip("<p>Hello</p>", FIELDS), ("<p>Hello</p>", None))

    def test_a_real_expression_gives_no_template_and_says_why(self):
        for html in ('[% upper("nombre") %]', '[% "nombre" || \' km\' %]', "[% @layer_name %]", '[% "nope" %]'):
            template, problem = popup.convert_map_tip(html, FIELDS)
            self.assertIsNone(template, html)
            self.assertIn("attribute table", problem)

    def test_too_long_is_refused(self):
        template, problem = popup.convert_map_tip("x" * (popup.MAX_TEMPLATE_CHARS + 1), FIELDS)
        self.assertIsNone(template)
        self.assertIn("too long", problem)


class ValueMapTests(unittest.TestCase):
    def test_list_shape_maps_stored_value_to_label(self):
        config = {"map": [{"Urban": "1"}, {"Rural": "2"}]}
        self.assertEqual(popup.value_map_from_config(config), {"1": "Urban", "2": "Rural"})

    def test_older_dict_shape(self):
        self.assertEqual(popup.value_map_from_config({"map": {"Yes": "Y", "No": "N"}}), {"Y": "Yes", "N": "No"})

    def test_the_null_marker_and_junk_are_ignored(self):
        config = {"map": [{"(no value)": "{2839923C-8B7D-417C-9D5C-0A3B6FA7F1F0}"}, {"A": 1}, "junk"]}
        self.assertEqual(popup.value_map_from_config(config), {"1": "A"})
        for bad in (None, {}, {"map": None}, "text", {"map": 5}):
            self.assertEqual(popup.value_map_from_config(bad), {})


class FieldWidgetTests(unittest.TestCase):
    def test_widgets(self):
        self.assertEqual(popup.field_widget_info("Hidden", {}), {"hidden": True})
        self.assertEqual(popup.field_widget_info("ValueMap", {"map": [{"A": "1"}]}), {"valueMap": {"1": "A"}})
        self.assertEqual(popup.field_widget_info("ValueMap", {"map": []}), {})
        self.assertEqual(popup.field_widget_info("TextEdit", {}), {})

    def test_merge_field_info(self):
        merged = popup.merge_field_info(
            {"a": {"alias": "A"}, "b": {}},
            {"a": {"hidden": True}, "c": {"valueMap": {"1": "x"}}},
            None,
        )
        self.assertEqual(merged, {"a": {"alias": "A", "hidden": True}, "c": {"valueMap": {"1": "x"}}})



class TemporalTests(unittest.TestCase):
    FIELDS = ["name", "founded", "closed"]

    def test_an_instant_in_one_field(self):
        self.assertEqual(
            popup.temporal_from_properties(True, "ModeFeatureDateTimeInstantFromField", "founded", "", self.FIELDS),
            {"startField": "founded"},
        )

    def test_start_and_end_fields(self):
        self.assertEqual(
            popup.temporal_from_properties(
                True, "ModeFeatureDateTimeStartAndEndFromFields", "founded", "closed", self.FIELDS
            ),
            {"startField": "founded", "endField": "closed"},
        )

    def test_nothing_to_filter_on(self):
        f = popup.temporal_from_properties
        self.assertIsNone(f(False, "ModeFeatureDateTimeInstantFromField", "founded", "", self.FIELDS))
        self.assertIsNone(f(True, "ModeFixedTemporalRange", "founded", "", self.FIELDS))
        self.assertIsNone(f(True, "ModeFeatureDateTimeInstantFromField", "gone", "", self.FIELDS))
        self.assertIsNone(f(True, "ModeFeatureDateTimeStartAndEndFromFields", "founded", "gone", self.FIELDS))
        self.assertIsNone(f(True, None, "founded", "", self.FIELDS))


if __name__ == "__main__":
    unittest.main()
