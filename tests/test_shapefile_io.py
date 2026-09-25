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

    def test_doctype_rejected_without_parsing(self):
        # Entity-expansion attacks (billion laughs, quadratic blowup) require
        # a DOCTYPE to declare their custom ENTITYs — QGIS's own SLD export
        # never emits one, so this is rejected the same way invalid XML is
        # (unchanged, no raise) rather than ever reaching ET.fromstring().
        bomb = (
            '<?xml version="1.0"?>'
            "<!DOCTYPE lolz [<!ENTITY lol \"lol\"><!ENTITY lol2 \"&lol;&lol;&lol;\">]>"
            "<Rule><PropertyName>&lol2;</PropertyName></Rule>"
        )
        changed, new_text = shapefile_io._rewrite_sld_text(bomb, {"a": "b"})
        self.assertFalse(changed)
        self.assertEqual(new_text, bomb)

    def test_reserved_nsN_namespace_prefix_does_not_raise(self):
        # xml.etree.ElementTree.register_namespace() raises ValueError
        # ("Prefix format reserved for internal use") for any "nsN" prefix —
        # QGIS's own SLD export can emit exactly this for some symbology
        # (embedded SVG markers/graphics), which crashed the whole run with a
        # bare, undebuggable error message before this was guarded against.
        sld = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<StyledLayerDescriptor xmlns:ogc="http://www.opengis.net/ogc" '
            'xmlns:ns0="http://www.w3.org/1999/xlink" xmlns:ns12="http://example.com/other">'
            "<ogc:PropertyName>1er Apelli</ogc:PropertyName>"
            "</StyledLayerDescriptor>"
        )
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"1er Apelli": "f1erApelli"})
        self.assertTrue(changed)
        self.assertIn("f1erApelli", new_text)
        self.assertNotIn("1er Apelli", new_text)

    def test_default_namespace_stays_unprefixed(self):
        # QGIS's own SLD export always declares the SLD namespace as the *default*
        # (unprefixed) one -- xmlns="http://www.opengis.net/sld" on the root, with
        # NamedLayer/UserStyle/Rule/... left bare. Before this was fixed, rewriting
        # anything in a document like this silently re-prefixed every one of those
        # elements with an arbitrary "nsN:" on output (ET.tostring() has no way to
        # know an unregistered namespace was meant to stay unprefixed) -- a real SLD
        # corruption, not a cosmetic difference, and the actual cause of styles
        # failing to render in the generated app even though generation "succeeded".
        sld = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" '
            'xmlns:ogc="http://www.opengis.net/ogc" xmlns:se="http://www.opengis.net/se">'
            "<NamedLayer><UserStyle><se:FeatureTypeStyle><se:Rule>"
            "<ogc:PropertyName>TOTAL</ogc:PropertyName>"
            "</se:Rule></se:FeatureTypeStyle></UserStyle></NamedLayer>"
            "</StyledLayerDescriptor>"
        )
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"TOTAL": "total"})
        self.assertTrue(changed)
        self.assertIn("total", new_text)
        self.assertNotIn("ns0:", new_text)
        self.assertIn("<StyledLayerDescriptor ", new_text)
        self.assertIn("<NamedLayer>", new_text)
        self.assertIn("<UserStyle>", new_text)

    def test_default_namespace_survives_alongside_reserved_ns_prefix(self):
        # Combines both real-world quirks in one document: the default SLD
        # namespace (see the test above) plus a QGIS-emitted "ns0"-reserved prefix
        # (see test_reserved_nsN_namespace_prefix_does_not_raise) for an embedded
        # graphic reference.
        sld = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" '
            'xmlns:ogc="http://www.opengis.net/ogc" xmlns:ns0="http://www.w3.org/1999/xlink">'
            "<NamedLayer><ogc:PropertyName>1er Apelli</ogc:PropertyName></NamedLayer>"
            "</StyledLayerDescriptor>"
        )
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"1er Apelli": "f1erApelli"})
        self.assertTrue(changed)
        self.assertIn("f1erApelli", new_text)
        self.assertIn("<StyledLayerDescriptor ", new_text)
        self.assertIn("<NamedLayer>", new_text)

    def test_preserves_xml_declaration(self):
        sld = '<?xml version="1.0" encoding="UTF-8"?><Rule><PropertyName>a</PropertyName></Rule>'
        changed, new_text = shapefile_io._rewrite_sld_text(sld, {"a": "b"})
        self.assertTrue(changed)
        self.assertTrue(new_text.startswith('<?xml version="1.0" encoding="UTF-8"?>'))


class RealQgisSldFixturesTests(unittest.TestCase):
    """Regression fixtures captured verbatim from real `layer.saveSldStyle()`
    output (QGIS 4.2.2, headless PyQGIS), not hand-written approximations —
    see WORKLOG.md's "Workstream 3b/3c" entry. These lock in a "verify first"
    finding: QGIS already emits a plain, any-prefix `PropertyName` element for
    both a label's field and a categorized rule's filter, so the existing
    rewrite (built and tested above only against synthetic marker/filter SLD)
    already handles both without any code change — this class exists purely
    to make sure that stays true.
    """

    # A single symbol + a text-labeled rule for a point layer, labeled by the
    # (already DBF/DSL-safe, lowercase) field "nombre" — i.e. QGIS's default
    # `QgsVectorLayerSimpleLabeling` output, unmodified.
    LABELED_SLD = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" version="1.1.0" '
        'xmlns:ogc="http://www.opengis.net/ogc" xmlns:se="http://www.opengis.net/se" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.1.0/StyledLayerDescriptor.xsd">\n'
        '  <NamedLayer>\n    <se:Name>test</se:Name>\n    <UserStyle>\n      <se:Name>test</se:Name>\n'
        '      <se:FeatureTypeStyle>\n        <se:Rule>\n          <se:Name>Single symbol</se:Name>\n'
        '          <se:PointSymbolizer>\n            <se:Graphic>\n              <se:Mark>\n'
        '                <se:WellKnownName>circle</se:WellKnownName>\n                <se:Fill>\n'
        '                  <se:SvgParameter name="fill">#729b6f</se:SvgParameter>\n                </se:Fill>\n'
        '                <se:Stroke>\n                  <se:SvgParameter name="stroke">#232323</se:SvgParameter>\n'
        '                  <se:SvgParameter name="stroke-width">0.5</se:SvgParameter>\n                </se:Stroke>\n'
        '              </se:Mark>\n              <se:Size>7</se:Size>\n            </se:Graphic>\n'
        '          </se:PointSymbolizer>\n        </se:Rule>\n        <se:Rule>\n          <se:TextSymbolizer>\n'
        '            <se:Label>\n              <ogc:PropertyName>nombre</ogc:PropertyName>\n            </se:Label>\n'
        '            <se:Font>\n              <se:SvgParameter name="font-family">Segoe UI</se:SvgParameter>\n'
        '              <se:SvgParameter name="font-size">13</se:SvgParameter>\n            </se:Font>\n'
        '            <se:LabelPlacement>\n              <se:PointPlacement>\n                <se:AnchorPoint>\n'
        '                  <se:AnchorPointX>0.5</se:AnchorPointX>\n                  <se:AnchorPointY>0.5</se:AnchorPointY>\n'
        '                </se:AnchorPoint>\n              </se:PointPlacement>\n            </se:LabelPlacement>\n'
        '            <se:Fill>\n              <se:SvgParameter name="fill">#000000</se:SvgParameter>\n            </se:Fill>\n'
        '          </se:TextSymbolizer>\n        </se:Rule>\n      </se:FeatureTypeStyle>\n    </UserStyle>\n'
        '  </NamedLayer>\n</StyledLayerDescriptor>\n'
    )

    # A 3-category QgsCategorizedSymbolRenderer on an all-caps field "TOTAL" —
    # exactly the case core/layer_export.py's plan_exports comment warns about:
    # dsl-util.js lowercases every field deriving the generated entity's column
    # name, so an unrewritten "TOTAL" filter would reference a column that
    # doesn't exist and GeoServer would silently fall back to its own default
    # style for the whole layer.
    CATEGORIZED_SLD_RULE_TEMPLATE = (
        "        <se:Rule>\n          <se:Name>{value}</se:Name>\n          <se:Description>\n"
        "            <se:Title>{value}</se:Title>\n          </se:Description>\n"
        '          <ogc:Filter xmlns:ogc="http://www.opengis.net/ogc">\n            <ogc:PropertyIsEqualTo>\n'
        "              <ogc:PropertyName>TOTAL</ogc:PropertyName>\n              <ogc:Literal>{value}</ogc:Literal>\n"
        "            </ogc:PropertyIsEqualTo>\n          </ogc:Filter>\n          <se:PolygonSymbolizer>\n"
        '            <se:Fill>\n              <se:SvgParameter name="fill">{color}</se:SvgParameter>\n            </se:Fill>\n'
        '            <se:Stroke>\n              <se:SvgParameter name="stroke">#232323</se:SvgParameter>\n'
        '              <se:SvgParameter name="stroke-width">1</se:SvgParameter>\n'
        '              <se:SvgParameter name="stroke-linejoin">bevel</se:SvgParameter>\n            </se:Stroke>\n'
        "          </se:PolygonSymbolizer>\n        </se:Rule>\n"
    )
    CATEGORIZED_SLD = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" version="1.1.0" '
        'xmlns:ogc="http://www.opengis.net/ogc" xmlns:se="http://www.opengis.net/se" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.1.0/StyledLayerDescriptor.xsd">\n'
        '  <NamedLayer>\n    <se:Name>test</se:Name>\n    <UserStyle>\n      <se:Name>test</se:Name>\n'
        "      <se:FeatureTypeStyle>\n"
        + CATEGORIZED_SLD_RULE_TEMPLATE.format(value=5, color="#ff0000")
        + CATEGORIZED_SLD_RULE_TEMPLATE.format(value=15, color="#00ff00")
        + CATEGORIZED_SLD_RULE_TEMPLATE.format(value=25, color="#0000ff")
        + "      </se:FeatureTypeStyle>\n    </UserStyle>\n  </NamedLayer>\n</StyledLayerDescriptor>\n"
    )

    def test_label_property_name_untouched_when_field_already_safe(self):
        # "nombre" needs no DBF/DSL rename, so plan_exports' sld_rename_map
        # would be {} for it — confirm the rewrite is then a true no-op
        # (matters because _rewrite_element_text skips re-serializing
        # entirely when nothing changed, so this also guards against any
        # future change accidentally forcing a needless XML round-trip).
        changed, new_text = shapefile_io._rewrite_sld_text(self.LABELED_SLD, {})
        self.assertFalse(changed)
        self.assertEqual(new_text, self.LABELED_SLD)

    def test_label_property_name_is_rewritten_when_its_field_is_renamed(self):
        # Simulates a labeled field that *did* need a DBF-safe rename (e.g. a
        # field named "1er Apelli") — the label must track the same rename or
        # the generated style silently stops finding the field.
        changed, new_text = shapefile_io._rewrite_sld_text(self.LABELED_SLD, {"nombre": "f1erApelli"})
        self.assertTrue(changed)
        self.assertIn("<ogc:PropertyName>f1erApelli</ogc:PropertyName>", new_text)
        self.assertNotIn(">nombre<", new_text)
        # Everything else in the rule (mark, colors, font) must survive intact.
        self.assertIn("<se:WellKnownName>circle</se:WellKnownName>", new_text)
        self.assertIn('<se:SvgParameter name="fill">#729b6f</se:SvgParameter>', new_text)
        self.assertIn('<se:SvgParameter name="font-family">Segoe UI</se:SvgParameter>', new_text)

    def test_categorized_filter_property_name_rewritten_for_every_rule(self):
        changed, new_text = shapefile_io._rewrite_sld_text(self.CATEGORIZED_SLD, {"TOTAL": "total"})
        self.assertTrue(changed)
        self.assertEqual(new_text.count("<ogc:PropertyName>total</ogc:PropertyName>"), 3)
        self.assertNotIn(">TOTAL<", new_text)
        # The category values/colors themselves are untouched — only the
        # field reference changes, not the literal comparison values.
        for value, color in [(5, "#ff0000"), (15, "#00ff00"), (25, "#0000ff")]:
            self.assertIn(f"<ogc:Literal>{value}</ogc:Literal>", new_text)
            self.assertIn(f'<se:SvgParameter name="fill">{color}</se:SvgParameter>', new_text)


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

    def test_hatch_and_shape_names_become_geoserver_shapes(self):
        # QGIS writes bare "horline"/"slash"...; GeoServer draws nothing unless it is shape://
        for qgis_name, geoserver_name in (
            ("horline", "shape://horline"), ("line", "shape://vertline"),
            ("slash", "shape://slash"), ("backslash", "shape://backslash"),
            ("diamond", "square"), ("hexagon", "circle"), ("arrowhead", "triangle"), ("cross2", "x"),
        ):
            sld = f"<Mark><WellKnownName>{qgis_name}</WellKnownName></Mark>"
            _, new_text = self._rewrite(sld)
            self.assertIn(f">{geoserver_name}<", new_text, qgis_name)

    def test_every_qgis_marker_shape_maps_to_something_geoserver_knows(self):
        known = {"square", "circle", "triangle", "star", "cross", "x"}
        for name, target in shapefile_io.QGIS_ONLY_MARK_NAMES.items():
            self.assertTrue(target in known or target.startswith("shape://"), (name, target))

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


class ClampGraphicMarginsTests(unittest.TestCase):
    SLD = (
        '<se:PolygonSymbolizer><se:Fill><se:GraphicFill><se:Graphic><se:Mark/>'
        '<se:Size>{size}</se:Size></se:Graphic></se:GraphicFill></se:Fill>'
        '<se:VendorOption name="graphic-margin">{margin}</se:VendorOption></se:PolygonSymbolizer>'
    )

    def test_margin_larger_than_the_graphic_is_capped(self):
        # GeoServer draws nothing at all when a margin exceeds the graphic's size
        changed, text = shapefile_io.clamp_margins_text(self.SLD.format(size=4, margin="6.4 6.4"))
        self.assertTrue(changed)
        self.assertIn('graphic-margin">4 4<', text)

    def test_each_value_of_a_four_value_margin_is_capped(self):
        _, text = shapefile_io.clamp_margins_text(self.SLD.format(size=10, margin="2 12 3 30"))
        self.assertIn('graphic-margin">2 10 3 10<', text)

    def test_a_margin_that_fits_is_left_alone(self):
        changed, text = shapefile_io.clamp_margins_text(self.SLD.format(size=10, margin="8"))
        self.assertFalse(changed)
        self.assertIn('graphic-margin">8<', text)


class RenameFunctionsTests(unittest.TestCase):
    def test_qgis_function_names_become_geoserver_ones(self):
        sld = '<ogc:Filter><ogc:Function name="upper"><ogc:PropertyName>kind</ogc:PropertyName></ogc:Function></ogc:Filter>'
        changed, text = shapefile_io.rename_functions_text(sld)
        self.assertTrue(changed)
        self.assertIn('name="strToUpperCase"', text)

    def test_a_function_geoserver_already_knows_is_left_alone(self):
        sld = '<ogc:Function name="round"><ogc:PropertyName>v</ogc:PropertyName></ogc:Function>'
        changed, text = shapefile_io.rename_functions_text(sld)
        self.assertFalse(changed)
        self.assertEqual(text, sld)


if __name__ == "__main__":
    unittest.main()
