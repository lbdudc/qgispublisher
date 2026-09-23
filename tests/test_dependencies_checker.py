"""Unit tests for core.dependencies_checker — runnable outside QGIS:

    python -m unittest discover -s tests

Covers only the pure decisions (compare_versions, should_check_for_update); the
functions around them spawn subprocesses / touch the filesystem and are exercised
manually (see the plan's Verification section), matching the pure/adapter split
documented in core/layer_export.py and used by the other test modules here.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dependencies_checker as deps  # noqa: E402


class CompareVersionsTests(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(deps.compare_versions("1.1.5", "1.1.5"), 0)

    def test_older(self):
        self.assertEqual(deps.compare_versions("1.1.4", "1.1.5"), -1)

    def test_newer(self):
        self.assertEqual(deps.compare_versions("1.2.0", "1.1.5"), 1)

    def test_major_beats_minor_and_patch(self):
        self.assertEqual(deps.compare_versions("2.0.0", "1.99.99"), 1)

    def test_minor_beats_patch(self):
        self.assertEqual(deps.compare_versions("1.2.0", "1.1.99"), 1)

    def test_prerelease_suffix_ignored(self):
        self.assertEqual(deps.compare_versions("1.1.5-beta.1", "1.1.5"), 0)

    def test_none_or_empty_is_unknown(self):
        self.assertIsNone(deps.compare_versions(None, "1.1.5"))
        self.assertIsNone(deps.compare_versions("1.1.5", None))
        self.assertIsNone(deps.compare_versions("", "1.1.5"))

    def test_unparseable_is_unknown(self):
        self.assertIsNone(deps.compare_versions("not-a-version", "1.1.5"))


class ShouldCheckForUpdateTests(unittest.TestCase):
    def test_never_checked_before(self):
        self.assertTrue(deps.should_check_for_update(None, now_epoch=1_000_000))
        self.assertTrue(deps.should_check_for_update(0, now_epoch=1_000_000))

    def test_within_interval_skips(self):
        last_check = 1_000_000
        now = last_check + deps.UPDATE_CHECK_INTERVAL_SECONDS - 1
        self.assertFalse(deps.should_check_for_update(last_check, now))

    def test_at_interval_boundary_checks(self):
        last_check = 1_000_000
        now = last_check + deps.UPDATE_CHECK_INTERVAL_SECONDS
        self.assertTrue(deps.should_check_for_update(last_check, now))

    def test_past_interval_checks(self):
        last_check = 1_000_000
        now = last_check + deps.UPDATE_CHECK_INTERVAL_SECONDS * 3
        self.assertTrue(deps.should_check_for_update(last_check, now))

    def test_custom_interval(self):
        self.assertFalse(deps.should_check_for_update(1_000_000, 1_000_030, interval_seconds=60))
        self.assertTrue(deps.should_check_for_update(1_000_000, 1_000_060, interval_seconds=60))


if __name__ == "__main__":
    unittest.main()
