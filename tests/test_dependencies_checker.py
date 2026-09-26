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
from unittest import mock

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


class FindSshTests(unittest.TestCase):
    """QGIS on Windows starts with a PATH that leaves out Windows' OpenSSH: the CLI could not run ssh."""

    def test_found_on_path_is_left_alone(self):
        with mock.patch.object(deps.shutil, "which", return_value="/usr/bin/ssh"), mock.patch.dict(
            os.environ, {"PATH": "/usr/bin"}
        ):
            self.assertEqual(deps.find_ssh(), "/usr/bin/ssh")
            self.assertEqual(os.environ["PATH"], "/usr/bin")

    def test_missing_from_the_restricted_path_is_found_in_the_registry_path_and_added(self):
        ssh = r"C:\Windows\System32\OpenSSH\ssh.exe"

        def which(name, path=None):
            return ssh if path and "OpenSSH" in path and name == "ssh.exe" else None

        with mock.patch.object(deps.sys, "platform", "win32"), mock.patch.object(
            deps.shutil, "which", side_effect=which
        ), mock.patch.object(
            deps, "_windows_full_path", return_value=r"C:\Windows\System32;C:\Windows\System32\OpenSSH"
        ), mock.patch.dict(os.environ, {"PATH": r"C:\qgis\bin"}):
            self.assertEqual(deps.find_ssh(), ssh)
            self.assertIn(os.path.dirname(ssh), os.environ["PATH"])

    def test_not_installed_anywhere(self):
        with mock.patch.object(deps.sys, "platform", "linux"), mock.patch.object(deps.shutil, "which", return_value=None):
            self.assertIsNone(deps.find_ssh())


if __name__ == "__main__":
    unittest.main()
