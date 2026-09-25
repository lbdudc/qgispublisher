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


# Every reserved word gp-gis-dsl's grammar (GISGrammar.g4) lexes as a keyword
# token rather than a plain IDENTIFIER — both the ``TYPE`` production (the
# property-type keywords, which double as geometry-class names) and every
# other ``*_SYMBOL`` token spelled out as a run of case-insensitive letters
# (``fragment``-free ``L O N G``-style rules, which ANTLR matches
# case-insensitively). ``createEntityScheme`` (gispublisher's dsl-util.js)
# emits ``CREATE ENTITY <entity_name(layer_basename)>`` with no suffix at
# all — unlike layer/style identifiers, which always get a "Layer"/"Style"
# suffix — so a layer named e.g. "point" or "polygon" becomes
# ``CREATE ENTITY Point``/``CREATE ENTITY Polygon``, colliding with the
# grammar's own TYPE token and failing deep inside ANTLR with an opaque
# "no viable alternative" error instead of a clear one. Kept as a literal
# set (not re-derived from the .g4 at runtime) since gisdsl is a separate,
# independently-versioned repo — resync by hand if GISGrammar.g4's keyword
# list changes.
RESERVED_DSL_WORDS = frozenset(
    word.lower()
    for word in (
        # TYPE production (property types / geometry classes)
        "Long", "Boolean", "Integer", "Double", "LocalDate", "String",
        "LineString", "Line", "MultiLineString", "Polygon", "MultiPolygon",
        "Point", "MultiPoint",
        # Other keyword tokens
        "Create", "Gis", "Entity", "Using", "Use", "Generate", "Identifier",
        "Relationship", "Display_String", "Required", "Unique",
        "Bidirectional", "Mapped_By", "Layer", "Tile", "GeoJson",
        "GeometryType", "As", "Url", "StyleLayerDescriptor", "Editable",
        "FillColor", "StrokeColor", "FillOpacity", "StrokeOpacity",
        "StrokeWidth", "Wms", "Style", "Is_Base_Layer", "Hidden", "Sortable",
        "Map", "Set", "Deployment", "UrlWms", "LayerName", "Format", "Crs",
        "BboxCrs", "MinX", "MinY", "MaxX", "MaxY", "Queryable",
        "Attribution", "Version", "Raster",
    )
)


def collides_with_dsl_keyword(layer_basename):
    """True if ``entity_name(layer_basename)`` (what ``CREATE ENTITY`` will
    actually emit) is one of gp-gis-dsl's own reserved keywords — e.g. a
    layer named "point", "Polygon" or "entity" — a real, previously
    found-but-not-fixed generation failure (see WORKLOG.md). Comparison is
    case-insensitive to match ANTLR's own case-insensitive keyword lexing.
    """
    return entity_name(layer_basename).lower() in RESERVED_DSL_WORDS


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


def entity_property_name(field_name):
    """The property name the generated app exposes for a field: what its REST API and
    TSV export use (a chart's field references must match this).

    Unlike ``attribute_name`` (the lowercase DB column, which SLD styles refer to), the
    entity property is lowerCamelCase — ``obs_date`` is exposed as ``obsDate``.
    """
    return lower_camel_case(attribute_name(field_name))


_VALID_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NON_IDENTIFIER_CHARS = re.compile(r"[^A-Za-z0-9_]")
# Stricter than _NON_IDENTIFIER_CHARS: also excludes underscore, for contexts
# (docker_safe_app_name) where underscore itself is the unsafe character.
_NON_ALNUM_CHAR = re.compile(r"[^A-Za-z0-9]")

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


def suggest_app_name(name):
    """A DSL-safe suggestion for an invalid application name.

    gispublisher's dsl-util.js interpolates config.name directly into
    ``CREATE GIS <name> USING 4326;`` with no sanitization at all, so a name with
    spaces or punctuation (e.g. a QGIS project title) produces invalid DSL and the
    run fails deep inside the CLI's ANTLR parser. Used by the plugin to offer a
    fix-up rather than let that happen; unlike safe_field_name, there's no length
    limit to enforce here (DBF's 10-character cap doesn't apply to an app name).
    """
    ascii_name = normalize_diacritics(name or "")
    ascii_name = _NON_IDENTIFIER_CHARS.sub("_", ascii_name).strip("_")
    if not ascii_name or ascii_name[0].isdigit():
        ascii_name = "App_" + ascii_name
    return ascii_name or "App"


def docker_safe_app_name(name):
    """The app name, transformed so it's safe to embed in Docker container names
    and hostnames the generated docker-compose stack derives from it (the
    project name becomes e.g. "<name>-geoserver", used as the Host header on
    every server-to-GeoServer REST call).

    A DSL-valid app name (see is_valid_dsl_identifier) is allowed to contain
    underscores, but Tomcat's strict HTTP Host-header parser rejects any
    hostname containing one outright (IllegalArgumentException: "The character
    [_] is never valid in a domain name") -- silently breaking *every* call the
    generated server makes to GeoServer, with no error surfaced anywhere except
    the server's own logs, and no data or styles ever reaching GeoServer as a
    result. Swapping underscores for hyphens doesn't help either: hyphens
    aren't valid in a DSL identifier. The only character set safe for both is
    letters and digits alone, so this removes every separator via camelCasing
    (e.g. "demo_tfm_qgis_1051" -> "DemoTfmQgis1051") rather than substituting
    one unsafe character for another.
    """
    # upper_camel_case's separator-collapsing regex needs a character *after*
    # each separator run to consume it, so a trailing separator run (or an
    # input that's separators only, e.g. "  ") can survive untouched -- strip
    # whatever's left explicitly rather than assume the result is already
    # alphanumeric-only.
    camel = _NON_ALNUM_CHAR.sub("", upper_camel_case(name))
    # upper_camel_case also doesn't guard against a leading digit (see its
    # docstring); is_valid_dsl_identifier requires the result not start with
    # one either way.
    if not camel or camel[0].isdigit():
        camel = "App" + camel
    return camel


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
    # The generator derives the entity name from this and drops any accented letter
    # ("Árboles" would become "rboles"), so the accents are stripped here, the same way
    # spl-js-engine's normalize() does, and every later name stays consistent with it.
    candidate = normalize_diacritics(preferred or "") or "layer"
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


def dsl_safe_identifier(name, fallback_prefix="g"):
    """A DSL-safe (letters/digits/underscore, not digit-first) identifier
    derived from an arbitrary QGIS group name, for use as a staged
    subdirectory name — the CLI treats a staged subfolder's basename as a
    `CREATE SORTABLE MAP <identifier>` DSL identifier directly (see
    gispublisher's `main.js`: `path.basename(entryPath)`), so this has to be
    both filesystem-safe *and* DSL-identifier-safe, unlike a plain staged
    layer basename. Mirrors `suggest_app_name`'s approach (diacritics
    stripped, unsafe characters collapsed to underscore) but with a neutral
    fallback prefix instead of "App_", since this never reaches the user as
    an app name.
    """
    ascii_name = normalize_diacritics(name or "")
    ascii_name = _NON_IDENTIFIER_CHARS.sub("_", ascii_name).strip("_")
    if not ascii_name:
        return fallback_prefix
    if ascii_name[0].isdigit():
        ascii_name = f"{fallback_prefix}_{ascii_name}"
    return ascii_name


# Subdirectory names the staging root itself reserves for something other
# than a QGIS group: gispublisher_runner.py's own charts_temp_dir/
# models_temp_dir siblings of the per-group directories, plus gispublisher's
# own main.js getDirectories(), which excludes an "output" entry outright
# (it's where the CLI writes the generated product). Staging happens on
# Windows, where the filesystem is case-insensitive, so a QGIS group
# literally named "Output", "Charts" or "Models" would otherwise land right
# on top of one of these and corrupt or silently lose its own or the
# reserved directory's contents.
RESERVED_STAGING_DIRNAMES = frozenset({"output", "charts", "models", "branding"})


def assign_group_dirnames(group_names):
    """The single authority for "what subdirectory will this QGIS group's
    layers be staged under" — `group_names` is an ordered iterable of the
    *distinct* group names actually in use (e.g. from
    `project_manifest.describe_layer_tree`'s `group` values, deduplicated in
    first-seen order). Returns `{group_name: dirname}`, each dirname a
    `dsl_safe_identifier` deduplicated case-insensitively against its
    siblings via the same collision-avoidance rule as
    `assign_staged_basenames` (a QGIS project can easily have two group names
    that collapse to the same identifier once diacritics/punctuation are
    stripped, e.g. "Água" and "Agua") — and against RESERVED_STAGING_DIRNAMES,
    seeded into `used` upfront so a group named "Output"/"Charts"/"Models"
    gets suffixed away from the plugin's own reserved staging directories
    exactly like any other name collision, rather than silently colliding
    with them.
    """
    used = set(RESERVED_STAGING_DIRNAMES)
    result = {}
    for name in group_names:
        dirname = staged_basename(dsl_safe_identifier(name), used)
        used.add(dirname)
        result[name] = dirname
    return result


def starts_with_digit(text):
    """True if the name begins with a digit, a case the JS naming helpers do not
    handle robustly (the generator's ``upperCamelCase`` slicing bug only triggers
    on names starting with "0", but any digit-prefixed identifier is likely to fail
    downstream, e.g. as a Java class name), so callers should warn rather than trust
    the generated name blindly.
    """
    return bool(text) and text[0].isdigit()
