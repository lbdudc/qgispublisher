"""Unit tests for the QGIS-free helpers of core.style_prep:

    python -m unittest discover -s tests

The renderer/labelling rewriting itself needs real QGIS layers and is exercised by
rendering a project with every kind of symbology (see the e2e notes in WORKLOG.md).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import style_prep  # noqa: E402


class NegatedSiblingsTests(unittest.TestCase):
    def test_else_is_none_of_the_sibling_filters(self):
        self.assertEqual(
            style_prep.negated_siblings(['"a" = 1', '"b" > 2']),
            'NOT (("a" = 1) OR ("b" > 2))',
        )

    def test_blank_and_else_siblings_are_ignored(self):
        self.assertEqual(style_prep.negated_siblings(["", None, "ELSE", '"a" = 1']), 'NOT (("a" = 1))')

    def test_nothing_to_negate_gives_none(self):
        self.assertIsNone(style_prep.negated_siblings(["", None]))


class LabelExpressionTests(unittest.TestCase):
    """Labels that need computing become one QGIS expression, evaluated per feature at export."""

    def test_quote_field(self):
        self.assertEqual(style_prep.quote_field("name"), '"name"')
        self.assertEqual(style_prep.quote_field('a"b'), '"a""b"')

    def test_first_matching_rule_wins_and_an_unfiltered_rule_is_the_fallback(self):
        rules = [('"pop" > 100', '"name"'), ('"pop" > 10', '"code"'), ("", '"id"'), ('"x" = 1', '"never"')]
        self.assertEqual(
            style_prep.label_case_expression(rules),
            'CASE WHEN ("pop" > 100) THEN ("name") WHEN ("pop" > 10) THEN ("code") ELSE ("id") END',
        )

    def test_else_rule_is_the_fallback_too(self):
        self.assertEqual(
            style_prep.label_case_expression([('"a" = 1', '"x"'), ("ELSE", '"y"')]),
            'CASE WHEN ("a" = 1) THEN ("x") ELSE ("y") END',
        )

    def test_a_single_unfiltered_rule_is_just_its_text(self):
        self.assertEqual(style_prep.label_case_expression([("", "concat(\"a\", \"b\")")]), 'concat("a", "b")')
        self.assertEqual(style_prep.label_case_expression([("  ", '"a"')]), '"a"')

    def test_no_rules(self):
        self.assertIsNone(style_prep.label_case_expression([]))

    def test_rules_without_a_fallback_label_nothing_else(self):
        self.assertEqual(
            style_prep.label_case_expression([('"a" = 1', '"x"')]), 'CASE WHEN ("a" = 1) THEN ("x") END'
        )

    def test_nested_rule_needs_its_parents_filter_too(self):
        self.assertEqual(style_prep.combine_filters('"a" = 1', '"b" = 2'), '("a" = 1) AND ("b" = 2)')
        self.assertEqual(style_prep.combine_filters("", '"b" = 2'), '"b" = 2')
        self.assertEqual(style_prep.combine_filters('"a" = 1', ""), '"a" = 1')
        self.assertEqual(style_prep.combine_filters("", ""), "")

    def test_the_label_column_is_a_valid_shapefile_field_name(self):
        self.assertLessEqual(len(style_prep.LABEL_FIELD), 10)
        self.assertEqual(style_prep.LABEL_FIELD, style_prep.LABEL_FIELD.lower())
        self.assertTrue(style_prep.LABEL_FIELD.replace("_", "").isalnum())


class MixColorTests(unittest.TestCase):
    def test_midpoint_of_two_colors(self):
        self.assertEqual(style_prep.mix_hex((255, 255, 178, 255), (189, 0, 38, 255)), (222, 128, 108, 255))


if __name__ == "__main__":
    unittest.main()
