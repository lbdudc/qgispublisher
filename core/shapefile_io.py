"""QGIS-free byte/text-level helpers for patching a staged shapefile's field names.

Kept separate from gispublisher_runner.py (which imports qgis.core at module level)
so these — the riskiest code in the plugin, since they patch bytes in place — can be
covered directly by tests/test_shapefile_io.py without a QGIS runtime.
"""

import os
import re
import struct
import xml.etree.ElementTree as ET  # nosec B405 - the one fromstring() call site rejects any DOCTYPE first; see _DOCTYPE_RE

_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*")
# A DOCTYPE is required syntax for the classic XML entity-expansion attacks
# (billion laughs, quadratic blowup) — both declare their custom ENTITYs
# inside one. QGIS's own SLD export never emits a DOCTYPE, so rejecting any
# input that has one is a free, dependency-free mitigation (see
# _rewrite_element_text's early-return on a match) instead of pulling in
# defusedxml as a hard runtime dependency for a QGIS plugin.
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)
_XMLNS_DECL_RE = re.compile(r'xmlns:([A-Za-z_][\w.-]*)="([^"]*)"')
# The *default* (unprefixed) namespace declaration — QGIS's own SLD export always
# uses this form for the SLD namespace itself (``xmlns="http://www.opengis.net/sld"``
# on the root element, with NamedLayer/UserStyle/Rule/... left unprefixed). The
# `\b` + literal "xmlns=" only matches when there's no colon in between, so this
# never doubles up with _XMLNS_DECL_RE above.
_DEFAULT_XMLNS_DECL_RE = re.compile(r'\bxmlns="([^"]*)"')
# xml.etree.ElementTree reserves any "nsN" prefix (N = digits) for its own
# auto-generated namespace prefixes: ET.register_namespace() raises
# ValueError("Prefix format reserved for internal use") if asked to register
# one explicitly. QGIS's own SLD export can emit exactly this kind of
# auto-generated prefix for some symbology (embedded SVG markers/graphics), so
# _rewrite_element_text skips registering those rather than letting a staged
# layer's own style crash the whole run.
_RESERVED_NS_PREFIX_RE = re.compile(r"^ns\d+$")
_PROPERTY_NAME_LOCALNAMES = {"PropertyName"}
_WELL_KNOWN_NAME_LOCALNAMES = {"WellKnownName"}

# QGIS writes several of its own internal SimpleMarker shape identifiers straight
# into WellKnownName instead of a standard SLD/SE mark name. GeoServer's core mark
# renderer only understands the OGC-standard set (square, circle, triangle, star,
# cross, x) plus a couple of its own extensions, and fails the *entire* GetMap
# request for the layer — not just that one symbolizer — with "The specified mark
# <name> was not found!" for anything else. This maps the QGIS-only names we've
# actually hit in practice onto their closest GeoServer-supported equivalent; add to
# it as new unsupported names turn up rather than guessing the full QGIS shape
# catalog up front.
#
# Every shape QGIS can write (Qgis.MarkerShape) plus the names its line-pattern fills
# and brush styles use are covered here. GeoServer knows square, circle, triangle, star,
# cross and x, the hatch shapes ``shape://horline|vertline|slash|backslash`` and
# ``brush://denseN``; the rest become the nearest of those.
_TO_SQUARE = (
    "diamond", "diagonal_half_square", "half_square", "quarter_square", "square_with_corners",
    "rounded_square", "parallelogram_left", "parallelogram_right", "trapezoid", "shield",
)
_TO_TRIANGLE = (
    "equilateral_triangle", "left_half_triangle", "right_half_triangle",
    "arrow", "arrowhead", "filled_arrowhead",
)
_TO_CIRCLE = (
    "pentagon", "hexagon", "octagon", "decagon", "heart", "half_arc", "quarter_arc",
    "third_arc", "quarter_circle", "semi_circle", "third_circle",
)
QGIS_ONLY_MARK_NAMES = {
    "cross_fill": "cross",
    "cross2": "x",
    "asterisk_fill": "star",
    "star_diamond": "star",
    "horline": "shape://horline",
    "line": "shape://vertline",
    "slash": "shape://slash",
    "backslash": "shape://backslash",
    **{name: "square" for name in _TO_SQUARE},
    **{name: "triangle" for name in _TO_TRIANGLE},
    **{name: "circle" for name in _TO_CIRCLE},
}


def rewrite_dbf_field_names(dbf_path, field_names, rename_map):
    """Patch a staged shapefile's DBF field-name bytes in place per `rename_map`
    (original name -> new name, both <= naming.DBF_FIELD_NAME_MAX_LENGTH ASCII
    chars). Only the 11-byte name slot of each field descriptor is touched — types,
    lengths and data stay untouched — so this only ever changes how the generator's
    DSL parser sees the field, never the underlying data.

    `field_names` is `layer.fields()`'s original (QGIS-decoded) names, in order —
    descriptors are matched by *position* against it rather than by re-decoding each
    descriptor's raw name bytes and comparing strings. A field whose name QGIS
    decoded correctly (e.g. via its .cpg) can be stored on disk in an encoding that
    doesn't round-trip through a fixed guess like latin-1 (that mismatch is exactly
    why some field names are broken in the first place), so a byte-decode-and-compare
    lookup silently misses precisely the fields we need to fix. If the DBF doesn't
    have exactly as many field descriptors as `field_names`, nothing is written —
    safer to skip the rename than guess at alignment.
    """
    if not rename_map:
        return
    with open(dbf_path, "r+b") as f:
        header = f.read(32)
        header_size = struct.unpack("<H", header[8:10])[0]
        descriptor_offsets = []
        offset = 32
        while offset < header_size - 1:
            f.seek(offset)
            descriptor = f.read(32)
            if len(descriptor) < 32 or descriptor[0] == 0x0D:
                break
            descriptor_offsets.append(offset)
            offset += 32

        if len(descriptor_offsets) != len(field_names):
            return

        for offset, name in zip(descriptor_offsets, field_names):
            new_name = rename_map.get(name)
            if new_name:
                name_bytes = new_name.encode("ascii")[:10].ljust(11, b"\x00")
                f.seek(offset)
                f.write(name_bytes)


def rewrite_sld_field_references(sld_path, rename_map):
    """QGIS bakes the *original* field name into an exported SLD's PropertyName
    elements. When a field got renamed for the staged DBF (see
    rewrite_dbf_field_names), the SLD needs the same substitution — otherwise
    generation succeeds but the resulting style silently fails to match any rule
    that referenced the renamed field.

    Parses the SLD as XML and rewrites the text of every ``PropertyName`` element
    (any namespace prefix — ``PropertyName``, ``ogc:PropertyName``,
    ``se:PropertyName``, ...) whose exact text is a key in `rename_map`. Using real
    XML parsing rather than a literal ``<tag>old</tag>`` string match means an
    attribute-form or whitespaced PropertyName is still caught.
    """
    if not rename_map or not os.path.isfile(sld_path):
        return
    try:
        with open(sld_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return

    changed, new_text = _rewrite_element_text(text, _PROPERTY_NAME_LOCALNAMES, rename_map)
    if changed:
        with open(sld_path, "w", encoding="utf-8") as f:
            f.write(new_text)


def rewrite_unsupported_marks(sld_path):
    """Patch a staged SLD's WellKnownName elements in place, replacing any
    QGIS-only mark name (see QGIS_ONLY_MARK_NAMES) with a GeoServer-supported one.

    Unlike the field-reference rewrite this isn't conditional on any prior rename —
    QGIS emits these names regardless of what the source data looks like — so it
    always runs over every exported SLD.
    """
    if not os.path.isfile(sld_path):
        return
    try:
        with open(sld_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return

    changed, new_text = _rewrite_element_text(
        text, _WELL_KNOWN_NAME_LOCALNAMES, QGIS_ONLY_MARK_NAMES
    )
    if changed:
        with open(sld_path, "w", encoding="utf-8") as f:
            f.write(new_text)


def _rewrite_sld_text(text, rename_map):
    """The pure string-in/string-out half of rewrite_sld_field_references, split out
    so it's directly unit-testable without touching the filesystem.

    Returns (changed, new_text).
    """
    return _rewrite_element_text(text, _PROPERTY_NAME_LOCALNAMES, rename_map)


def _rewrite_element_text(text, localnames, value_map):
    """Replace the text of every element in `localnames` (matched by local name,
    any namespace prefix) whose exact stripped text is a key in `value_map`.

    Shared by the field-reference and mark-name rewrites — both are "parse as XML,
    swap an element's text by exact match, re-serialize" with a different element
    name and mapping. Returns (changed, new_text).
    """
    decl_match = _XML_DECL_RE.match(text)
    xml_decl = decl_match.group(0) if decl_match else ""

    # Without this, ET.tostring() below has no idea the SLD namespace was meant to
    # stay unprefixed, auto-assigns it "ns0" (or whatever the next free slot is),
    # and rewrites every NamedLayer/UserStyle/Rule/... element with that prefix —
    # a real, silent SLD corruption, not just a cosmetic difference, whenever any
    # rewrite in this function actually changes something. Must be registered
    # *before* the explicit-prefix loop below: an unprefixed declaration doesn't
    # collide with `xmlns:foo="..."` ones (see _DEFAULT_XMLNS_DECL_RE), but if a
    # document somehow declared the same URI both ways, the later, explicit
    # registration should win, matching what a reader would see as "the" prefix.
    default_match = _DEFAULT_XMLNS_DECL_RE.search(text)
    if default_match:
        ET.register_namespace("", default_match.group(1))

    for prefix, uri in _XMLNS_DECL_RE.findall(text):
        # See _RESERVED_NS_PREFIX_RE: registering this prefix would raise.
        # Local-name matching below doesn't depend on which prefix a namespace
        # keeps, so skipping it only changes what ET.tostring() prints for
        # *this* namespace in the re-serialized output, never what gets found
        # or rewritten.
        if _RESERVED_NS_PREFIX_RE.match(prefix):
            continue
        ET.register_namespace(prefix, uri)

    if _DOCTYPE_RE.search(text):
        return False, text

    try:
        root = ET.fromstring(text)  # nosec B314 - DOCTYPE rejected above, closing off entity-expansion attacks
    except ET.ParseError:
        return False, text

    changed = False
    for elem in root.iter():
        localname = elem.tag.rsplit("}", 1)[-1]
        if localname not in localnames:
            continue
        if elem.text is None:
            continue
        stripped = elem.text.strip()
        new_value = value_map.get(stripped)
        if new_value is not None and new_value != stripped:
            elem.text = elem.text.replace(stripped, new_value, 1)
            changed = True

    if not changed:
        return False, text

    body = ET.tostring(root, encoding="unicode")
    return True, xml_decl + body


_POLYGON_SYMBOLIZER_RE = re.compile(r"(<(?:\w+:)?PolygonSymbolizer>)(.*?)(</(?:\w+:)?PolygonSymbolizer>)", re.S)
_GRAPHIC_SIZE_RE = re.compile(r"<(?:\w+:)?GraphicFill>.*?<(?:\w+:)?Size>\s*([0-9.]+)\s*</(?:\w+:)?Size>", re.S)
_GRAPHIC_MARGIN_RE = re.compile(r'(<(?:\w+:)?VendorOption name="graphic-margin">)([^<]*)(</(?:\w+:)?VendorOption>)')


def clamp_margins_text(text):
    """Cap each ``graphic-margin`` of a pattern fill at the size of its graphic.

    QGIS spaces the marks of a point-pattern fill with a margin around each one, but
    GeoServer draws *nothing* when a margin is larger than the graphic. Capping keeps the
    pattern visible (a little denser than in QGIS) instead of the layer vanishing.
    Returns (changed, new_text).
    """
    changed = False

    def fix_symbolizer(match):
        nonlocal changed
        head, body, tail = match.groups()
        size_match = _GRAPHIC_SIZE_RE.search(body)
        if not size_match:
            return match.group(0)
        size = float(size_match.group(1))

        def fix_margin(m):
            nonlocal changed
            values = []
            for token in m.group(2).split():
                try:
                    value = float(token)
                except ValueError:
                    return m.group(0)
                if value > size:
                    changed = True
                    value = size
                values.append(f"{value:g}")
            return m.group(1) + " ".join(values) + m.group(3)

        return head + _GRAPHIC_MARGIN_RE.sub(fix_margin, body) + tail

    new_text = _POLYGON_SYMBOLIZER_RE.sub(fix_symbolizer, text)
    return changed, new_text


def clamp_graphic_margins(sld_path):
    """Apply ``clamp_margins_text`` to a staged SLD file in place."""
    if not os.path.isfile(sld_path):
        return
    try:
        with open(sld_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    changed, new_text = clamp_margins_text(text)
    if changed:
        with open(sld_path, "w", encoding="utf-8") as f:
            f.write(new_text)


# QGIS writes an expression function under its own name inside a filter; GeoServer knows
# its own names, and refuses to create a style that calls an unknown function (the layer
# then has no style at all). The ones with the same arguments are renamed.
QGIS_FUNCTION_NAMES = {
    "upper": "strToUpperCase",
    "lower": "strToLowerCase",
    "length": "strLength",
    "trim": "strTrim",
    "concat": "Concatenate",
    "to_int": "parseInt",
    "to_real": "parseDouble",
}
_FUNCTION_NAME_RE = re.compile(r'(<(?:\w+:)?Function name=")([^"]+)(")')


def rename_functions_text(text):
    """Rename QGIS filter functions to their GeoServer names. Returns (changed, new_text)."""
    changed = False

    def rename(match):
        nonlocal changed
        target = QGIS_FUNCTION_NAMES.get(match.group(2))
        if target is None:
            return match.group(0)
        changed = True
        return match.group(1) + target + match.group(3)

    new_text = _FUNCTION_NAME_RE.sub(rename, text)
    return changed, new_text


def rename_sld_functions(sld_path):
    """Apply ``rename_functions_text`` to a staged SLD file in place."""
    if not os.path.isfile(sld_path):
        return
    try:
        with open(sld_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    changed, new_text = rename_functions_text(text)
    if changed:
        with open(sld_path, "w", encoding="utf-8") as f:
            f.write(new_text)
