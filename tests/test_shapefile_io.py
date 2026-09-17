"""Unit tests for core.shapefile_io — runnable outside QGIS:

    python -m unittest discover -s tests

Covers the riskiest code in the plugin: in-place binary patching of a shapefile's
DBF field-name bytes, and the XML rewrite of SLD PropertyName references that must
stay in sync with it.
"""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import shapefile_io  # noqa: E402


def _build_minimal_dbf(field_names):
    """A syntactically valid, minimal DBF: a 32-byte file header, one 32-byte field
    descriptor per name (11-byte name + 21 bytes of type/length filler), a 0x0D
    terminator, and a single record matching the declared record length — just
    enough structure for rewrite_dbf_field_names to walk and patch.
    """
    header_size = 32 + 32 * len(field_names) + 1
    record_length = 1 + 10 * len(field_names)  # 1 deletion flag byte + 10 per field

    header = bytearray(32)
    header[0] = 0x03  # version
    struct.pack_into("<H", header, 8, header_size)
    struct.pack_into("<H", header, 10, record_length)

    descriptors = bytearray()
    for name in field_names:
        desc = bytearray(32)
        name_bytes = name.encode("ascii")[:10].ljust(11, b"\x00")
        desc[0:11] = name_bytes
        desc[11] = ord("C")  # character field
        desc[16] = 10  # length
        descriptors += desc

    record = b" " * record_length
    return bytes(header) + bytes(descriptors) + b"\x0d" + record


def _read_descriptor_names(dbf_path, count):
    with open(dbf_path, "rb") as f:
        f.seek(32)
        names = []
        for _ in range(count):
            desc = f.read(32)
            names.append(desc[0:11].rstrip(b"\x00").decode("ascii"))
        return names


class RewriteDbfFieldNamesTests(unittest.TestCase):
    def _write_temp_dbf(self, field_names):
        fd, path = tempfile.mkstemp(suffix=".dbf")
        with os.fdopen(fd, "wb") as f:
            f.write(_build_minimal_dbf(field_names))
        self.addCleanup(lambda: os.remove(path))
        return path

    def test_patches_only_renamed_fields_by_position(self):
        original = ["1er Apelli", "descriptio", "poblacion"]
        path = self._write_temp_dbf(original)
        rename_map = {"1er Apelli": "f1erApelli"}

        shapefile_io.rewrite_dbf_field_names(path, original, rename_map)

        self.assertEqual(
            _read_descriptor_names(path, len(original)),
            ["f1erApelli", "descriptio", "poblacion"],
        )

    def test_noop_when_rename_map_is_empty(self):
        original = ["name", "pop"]
        path = self._write_temp_dbf(original)
        before = _read_descriptor_names(path, len(original))

        shapefile_io.rewrite_dbf_field_names(path, original, {})

        self.assertEqual(_read_descriptor_names(path, len(original)), before)

    def test_skips_write_when_descriptor_count_mismatches(self):
        original = ["name", "pop"]
        path = self._write_temp_dbf(original)
        before = _read_descriptor_names(path, len(original))

        # field_names claims 3 fields but the DBF only has 2 descriptors.
        shapefile_io.rewrite_dbf_field_names(path, ["name", "pop", "extra"], {"extra": "ext"})

        self.assertEqual(_read_descriptor_names(path, len(original)), before)

    def test_only_touches_the_11_byte_name_slot(self):
        original = ["oldname"]
        path = self._write_temp_dbf(original)
        shapefile_io.rewrite_dbf_field_names(path, original, {"oldname": "newname"})

        with open(path, "rb") as f:
            f.seek(32)
            descriptor = f.read(32)
        self.assertEqual(descriptor[0:11].rstrip(b"\x00"), b"newname")
        self.assertEqual(descriptor[11], ord("C"))  # type byte untouched
        self.assertEqual(descriptor[16], 10)  # length byte untouched


class RewriteSldTextTests(unittest.TestCase):
    def test_rewrites_ogc_property_name(self):
        sld = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<StyledLayerDescriptor xmlns:ogc="http://www.opengis.net/ogc">'
            '<ogc:PropertyName>1er Apelli</ogc:PropertyName>'
            '</StyledLayerDescriptor>'
        )
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"1er Apelli": "f1erApelli"})
        self.assertTrue(changed)
        self.assertIn("f1erApelli", new_text)
        self.assertNotIn("1er Apelli", new_text)

    def test_rewrites_bare_property_name_without_prefix(self):
        sld = "<Rule><PropertyName>oldname</PropertyName></Rule>"
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"oldname": "newname"})
        self.assertTrue(changed)
        self.assertIn("newname", new_text)

    def test_no_change_when_no_field_referenced(self):
        sld = "<Rule><PropertyName>untouched</PropertyName></Rule>"
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"oldname": "newname"})
        self.assertFalse(changed)
        self.assertEqual(new_text, sld)

    def test_invalid_xml_is_left_untouched(self):
        changed, new_text = shapefile_io._rewrite_sld_text("<not-xml", {"a": "b"})
        self.assertFalse(changed)
        self.assertEqual(new_text, "<not-xml")

    def test_preserves_xml_declaration(self):
        sld = '<?xml version="1.0" encoding="UTF-8"?><Rule><PropertyName>a</PropertyName></Rule>'
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"a": "b"})
        self.assertTrue(changed)
        self.assertTrue(new_text.startswith('<?xml version="1.0" encoding="UTF-8"?>'))


class RewriteUnsupportedMarksTests(unittest.TestCase):
    def _rewrite(self, sld):
        return shapefile_io._rewrite_element_text(
            sld, shapefile_io._WELL_KNOWN_NAME_LOCALNAMES, shapefile_io.QGIS_ONLY_MARK_NAMES
        )

    def test_rewrites_cross_fill_to_cross(self):
        sld = (
            '<se:Mark xmlns:se="http://www.opengis.net/se">'
            "<se:WellKnownName>cross_fill</se:WellKnownName>"
            "</se:Mark>"
        )
        changed, new_text = self._rewrite(sld)
        self.assertTrue(changed)
        self.assertIn("cross</", new_text)
        self.assertNotIn("cross_fill", new_text)

    def test_standard_mark_name_is_left_untouched(self):
        sld = "<Mark><WellKnownName>circle</WellKnownName></Mark>"
        changed, new_text = self._rewrite(sld)
        self.assertFalse(changed)
        self.assertEqual(new_text, sld)

    def test_rewrite_unsupported_marks_patches_file_in_place(self):
        fd, path = tempfile.mkstemp(suffix=".sld")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("<Mark><WellKnownName>cross_fill</WellKnownName></Mark>")
        self.addCleanup(lambda: os.remove(path))

        shapefile_io.rewrite_unsupported_marks(path)

        with open(path, encoding="utf-8") as f:
            self.assertIn("cross</WellKnownName>", f.read())

    def test_rewrite_unsupported_marks_noop_when_file_missing(self):
        # Must not raise for a layer whose SLD export failed upstream.
        shapefile_io.rewrite_unsupported_marks("/no/such/file.sld")


if __name__ == "__main__":
    unittest.main()
