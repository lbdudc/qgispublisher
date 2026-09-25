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


class MixColorTests(unittest.TestCase):
    def test_midpoint_of_two_colors(self):
        self.assertEqual(style_prep.mix_hex((255, 255, 178, 255), (189, 0, 38, 255)), (222, 128, 108, 255))


if __name__ == "__main__":
    unittest.main()
