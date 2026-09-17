"""Naming helpers that mirror the identifiers @lbdudc/gis-publisher derives downstream.

These are direct ports of the JS helpers used by the generator, so that anything the
plugin computes (entity names, REST URL segments, attribute names) matches what the
generated application actually exposes:

- ``upper_camel_case`` / ``lower_camel_case`` port ``gis-publisher/src/str-util.js``.
- ``entity_name`` mirrors how ``dsl-util.js`` turns a shapefile basename into a
  ``CREATE ENTITY <Name>`` identifier.
- ``entity_url_segment`` mirrors the pluralisation used by the generated app's REST API
  and by the Chart Viewer's entity picker (``mini-lps/src/platform/extra.js``'s
  ``pluralize()`` is literally ``name + "s"``, applied to the *lower*-camel entity name).
- ``attribute_name`` mirrors the DBF-column-to-entity-attribute mapping in
  ``dsl-util.js`` (lowercased, with ``id`` renamed to ``id2`` since the entity already
  has its own identifier field).
"""

import os
import re
import unicodedata
import urllib.parse

_NON_ALNUM_RUN = re.compile(r"[^a-zA-Z0-9]+(.)")


def lower_camel_case(text):
    """Port of str-util.js's lowerCamelCase: lowercase, then camel-case on any run
    of non-alphanumeric separators, capitalizing the character that follows them."""
    if not text:
        return text
    lowered = text.lower()
    return _NON_ALNUM_RUN.sub(lambda m: m.group(1).upper(), lowered)


def upper_camel_case(text):
    """Port of str-util.js's upperCamelCase: lowerCamelCase with the first letter
    capitalized.

    Note: the original JS has a bug for names starting with a digit
    (``str.startsWith(0)`` coerces ``0`` to ``"0"`` then always evaluates falsy for a
    real string check... in practice it never trims anything meaningful, so we do not
    replicate it here). See ``warn_if_digit_prefixed`` for surfacing the edge case
    instead of silently mimicking undefined behaviour.
    """
    camel = lower_camel_case(text)
    if not camel:
        return camel
    return camel[0].upper() + camel[1:]


def entity_name(layer_basename):
    """The ``CREATE ENTITY`` identifier the generator derives from a layer's file
    basename (no extension), e.g. "unemployment_by_district" -> "UnemploymentByDistrict".
    """
    return upper_camel_case(layer_basename)


def entity_url_segment(layer_basename):
    """The REST path segment / Chart Viewer entity id for a layer, e.g.
    "unemployment_by_district" -> "unemploymentByDistricts".

    Matches the generated app: the entity's lower-camel name with a trailing "s"
    appended (mini-lps's ``pluralize()`` is literally ``name + "s"``).
    """
    name = lower_camel_case(layer_basename)
    if not name:
        return name
    return name + "s"


def attribute_name(field_name):
    """The entity attribute name derived from a DBF/attribute field name.

    dsl-util.js lowercases every field and renames a field literally called ``id`` to
    ``id2``, since the entity's own identifier field already occupies ``id``. A field
    name the generator's DSL grammar can't parse as an identifier (leading digit,
    spaces, accents, punctuation — see ``is_valid_dsl_identifier``) is first run
    through ``safe_field_name``, mirroring the rename gispublisher_runner applies to
    the staged DBF before the CLI ever sees it, so this always matches what the
    generator actually exposes.
    """
    lowered = safe_field_name(field_name).lower()
    return "id2" if lowered == "id" else lowered


_VALID_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NON_IDENTIFIER_CHARS = re.compile(r"[^A-Za-z0-9_]")

# dBase/shapefile DBF field names are limited to 10 characters.
DBF_FIELD_NAME_MAX_LENGTH = 10


def is_valid_dsl_identifier(name):
    """Whether `name` is already a valid identifier for the generator's DSL grammar
    (letters/digits/underscore, not starting with a digit) — i.e. safe to send to
    the CLI unchanged.
    """
    return bool(name) and bool(_VALID_IDENTIFIER_RE.match(name))


def safe_field_name(field_name, max_length=DBF_FIELD_NAME_MAX_LENGTH):
    """A DBF-safe, DSL-safe identifier for `field_name`, used to rename a field
    before staging when it would otherwise break the generator's DSL parser (e.g.
    "1er Apelli" -> ANTLR's "no viable alternative" on a leading digit and a space).

    Returns `field_name` unchanged when it's already valid *and* already fits
    `max_length`, so well-formed fields keep their exact original name (and case) in
    the staged shapefile. A field name can be a perfectly valid DSL identifier and
    still be too long for a DBF field slot — this only happens for a layer exported
    from a source with no such limit (GeoPackage, PostGIS), since a field read
    straight from an existing shapefile can never violate the DBF limit itself.
    """
    if is_valid_dsl_identifier(field_name) and len(field_name) <= max_length:
        return field_name
    ascii_name = normalize_diacritics(field_name or "")
    ascii_name = _NON_IDENTIFIER_CHARS.sub("", ascii_name)
    if not ascii_name or ascii_name[0].isdigit():
        ascii_name = "f" + ascii_name
    return ascii_name[:max_length] or "field"


def rename_map_for_fields(field_names, max_length=DBF_FIELD_NAME_MAX_LENGTH):
    """``{original_name: staged_name}`` for the subset of `field_names` that need
    fixing up before staging (see ``safe_field_name``), deduplicated against every
    name in the layer (case-insensitively, matching DBF's own comparison) so a
    rename can never collide with a sibling field. Names that are already valid are
    left out entirely — callers should keep those as-is.
    """
    used = {(n or "").lower() for n in field_names}
    renamed = {}
    for name in field_names:
        safe = safe_field_name(name, max_length)
        if safe == name:
            continue
        candidate = safe
        suffix = 1
        while candidate.lower() in used and candidate.lower() != (name or "").lower():
            tag = str(suffix)
            candidate = safe[: max_length - len(tag)] + tag
            suffix += 1
        used.discard((name or "").lower())
        used.add(candidate.lower())
        renamed[name] = candidate
    return renamed


def normalize_diacritics(text):
    """Strip diacritics the way spl-js-engine's ``normalize()`` template helper does
    (NFKD decomposition, drop combining marks) before further casing.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_LAYERNAME_URI_RE = re.compile(r"[?&|]layername=([^|&]+)", re.IGNORECASE)


def preferred_basename_from_source(name, source):
    """Pure core of ``layer_source_basename`` — takes the layer's plain name/source
    strings instead of a QGIS layer object, so callers building a
    ``core.layer_export.LayerDescriptor`` (no QGIS import) can call this directly.

    Prefers an embedded ``layername=`` (present on GeoPackage/PostGIS-style URIs and
    far more descriptive than the container file's own name — without this, every
    layer from the same .gpkg would otherwise propose the same basename), then the
    source file's own basename (the shapefile case), then the QGIS layer name.

    This is a *preferred* name only, not guaranteed collision-free — see
    ``assign_staged_basenames``.
    """
    try:
        source = source or ""
        m = _LAYERNAME_URI_RE.search(source)
        if m:
            return urllib.parse.unquote(m.group(1))
        path = source.split("|")[0].split("?")[0]
        basename = os.path.splitext(os.path.basename(path))[0]
        return basename or name
    except Exception:
        return name


def layer_source_basename(layer):
    """``preferred_basename_from_source`` for a live QGIS layer object."""
    try:
        return preferred_basename_from_source(layer.name(), layer.source())
    except Exception:
        return layer.name()


def staged_basename(preferred, used_basenames):
    """A filesystem-safe basename for `preferred` that doesn't collide (compared
    case-insensitively, matching Windows filesystems and DBF's own field-name
    comparison) with anything in `used_basenames`. Does not mutate `used_basenames` —
    callers should add the returned name before resolving the next candidate.
    """
    candidate = preferred or "layer"
    used_lower = {u.lower() for u in used_basenames}
    if candidate.lower() not in used_lower:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}".lower() in used_lower:
        suffix += 1
    return f"{candidate}_{suffix}"


def assign_staged_basenames(candidates):
    """The single authority for "what basename will this layer be staged under".

    `candidates` is an ordered iterable of (key, preferred_basename) pairs — pass the
    same layers in the same order everywhere a basename is needed (actual staging in
    gispublisher_runner, and prediction in chart building/validation) so every caller
    agrees even when two layers' preferred names collide. Returns {key: basename}.
    """
    used = set()
    result = {}
    for key, preferred in candidates:
        name = staged_basename(preferred, used)
        used.add(name)
        result[key] = name
    return result


def starts_with_digit(text):
    """True if the name begins with a digit, a case the JS naming helpers do not
    handle robustly (the generator's ``upperCamelCase`` slicing bug only triggers
    on names starting with "0", but any digit-prefixed identifier is likely to fail
    downstream, e.g. as a Java class name), so callers should warn rather than trust
    the generated name blindly.
    """
    return bool(text) and text[0].isdigit()
