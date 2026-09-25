"""Unit tests for core.web_options (pure, runnable outside QGIS)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import web_options  # noqa: E402


class NormalizeColorTests(unittest.TestCase):
    def test_accepts_six_digit_hex_with_or_without_hash(self):
        self.assertEqual(web_options.normalize_color("#0B7A75"), "#0b7a75")
        self.assertEqual(web_options.normalize_color(" 0b7a75 "), "#0b7a75")

    def test_rejects_anything_else(self):
        for bad in ("", None, "red", "#abc", "#12345g", "#1234567"):
            self.assertIsNone(web_options.normalize_color(bad), bad)


class BuildOptionsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(
            web_options.build_options(None),
            {"search": True, "geocoder": False, "legend": True, "downloads": True},
        )

    def test_only_booleans_count(self):
        options = web_options.build_options({"search": False, "geocoder": "yes", "legend": 0})
        self.assertFalse(options["search"])
        self.assertFalse(options["geocoder"])  # "yes" is not a bool: the default
        self.assertTrue(options["legend"])  # 0 is not a bool either


class LogoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _file(self, name, size=10):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        return path

    def test_no_logo_is_fine(self):
        self.assertIsNone(web_options.logo_problem(""))
        self.assertIsNone(web_options.stage_logo("", self.dir))

    def test_problems(self):
        self.assertIn("not found", web_options.logo_problem(os.path.join(self.dir, "nope.png")))
        self.assertIn("PNG", web_options.logo_problem(self._file("logo.exe")))
        big = self._file("big.png", web_options.MAX_LOGO_BYTES + 1)
        self.assertIn("too big", web_options.logo_problem(big))
        self.assertIsNone(web_options.logo_problem(self._file("ok.PNG")))

    def test_stage_logo_copies_under_branding_with_a_fixed_name(self):
        source = self._file("My Logo (1).PNG", 5)
        staging = tempfile.mkdtemp()
        self.assertEqual(web_options.stage_logo(source, staging), "logo.png")
        self.assertTrue(os.path.isfile(os.path.join(staging, "branding", "logo.png")))

    def test_an_unusable_logo_is_not_staged(self):
        staging = tempfile.mkdtemp()
        self.assertIsNone(web_options.stage_logo(self._file("logo.exe"), staging))
        self.assertFalse(os.path.exists(os.path.join(staging, "branding")))


class BuildBrandingTests(unittest.TestCase):
    def test_only_what_is_set(self):
        self.assertEqual(web_options.build_branding(), {})
        self.assertEqual(
            web_options.build_branding("  Río   Alto ", "#ABCDEF", "esri-dark", "logo.png"),
            {"title": "Río Alto", "primaryColor": "#abcdef", "basemap": "esri-dark", "logo": "logo.png"},
        )

    def test_invalid_values_are_dropped(self):
        self.assertEqual(web_options.build_branding("", "blue", "nope", None), {})


class ProjectInfoExtrasTests(unittest.TestCase):
    def test_none_gives_the_default_options_and_no_branding(self):
        extras = web_options.project_info_extras(None, tempfile.mkdtemp())
        self.assertEqual(extras, {"options": web_options.build_options(None)})

    def test_branding_and_logo_are_included(self):
        source_dir = tempfile.mkdtemp()
        logo = os.path.join(source_dir, "a.svg")
        with open(logo, "wb") as f:
            f.write(b"<svg/>")
        staging = tempfile.mkdtemp()
        extras = web_options.project_info_extras(
            {"options": {"search": False}, "title": "T", "color": "#111111", "logo_path": logo},
            staging,
        )
        self.assertFalse(extras["options"]["search"])
        self.assertEqual(extras["branding"], {"title": "T", "primaryColor": "#111111", "logo": "logo.svg"})
        self.assertTrue(os.path.isfile(os.path.join(staging, "branding", "logo.svg")))


if __name__ == "__main__":
    unittest.main()
