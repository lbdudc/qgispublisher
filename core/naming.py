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
    ``id2``, since the entity's own identifier field already occupies ``id``.
    """
    lowered = (field_name or "").lower()
    return "id2" if lowered == "id" else lowered


def normalize_diacritics(text):
    """Strip diacritics the way spl-js-engine's ``normalize()`` template helper does
    (NFKD decomposition, drop combining marks) before further casing.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def layer_source_basename(layer):
    """The basename gispublisher_runner.py stages a vector layer's shapefile
    sidecars under, which is what the generator derives entity names from.

    Usually the same as ``layer.name()``, but not guaranteed (e.g. after a QGIS-side
    rename with the source file left untouched), so callers that need to predict the
    generator's entity name (chart building/validation) should prefer this over
    ``layer.name()``.
    """
    try:
        source = layer.source().split("|")[0]
        basename = os.path.splitext(os.path.basename(source))[0]
        return basename or layer.name()
    except Exception:
        return layer.name()


def starts_with_digit(text):
    """True if the name begins with a digit, a case the JS naming helpers do not
    handle robustly (the generator's ``upperCamelCase`` slicing bug only triggers
    on names starting with "0", but any digit-prefixed identifier is likely to fail
    downstream, e.g. as a Java class name), so callers should warn rather than trust
    the generated name blindly.
    """
    return bool(text) and text[0].isdigit()
