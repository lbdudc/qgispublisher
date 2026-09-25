"""What QGIS shows when you click a feature, as plain data for the generated app: the
map tip (an HTML template), which columns the attribute table hides, and the labels a
value map gives to stored codes.

Pure like ``core.project_manifest``: the QGIS reads are in ``layer_export.describe_layer``
and hand these functions plain values, so they are covered by ``tests/test_popup.py``.
"""

import re

# [% "field" %], [% field %] and [%"field"%]: the only expressions the generated app
# can fill in. Everything else in a map tip ([% upper(x) %], @variables, sub-queries)
# needs QGIS's expression engine.
_EXPRESSION_RE = re.compile(r"\[%(.*?)%\]", re.DOTALL)
_QUOTED_RE = re.compile(r'^"((?:[^"]|"")+)"$')
_BARE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Kept short: a popup is a few lines, and the template travels in the manifest
MAX_TEMPLATE_CHARS = 4000

WIDGET_VALUE_MAP = "ValueMap"
WIDGET_HIDDEN = "Hidden"


def _field_name(expression, field_names):
    text = expression.strip()
    match = _QUOTED_RE.match(text)
    name = match.group(1).replace('""', '"') if match else (text if _BARE_RE.match(text) else None)
    return name if name in field_names else None


def convert_map_tip(html, field_names):
    """A QGIS map tip as ``(template, problem)``.

    ``template`` is the HTML with every ``[% "field" %]`` written as ``{{field}}``;
    ``problem`` says why there is none: ``None`` for an empty map tip (no template, not
    a problem) or a sentence for one that needs QGIS's expression engine (any other
    expression, or a field the layer doesn't have) or is too long.
    """
    text = (html or "").strip()
    if not text:
        return None, None
    fields = set(field_names)
    unsupported = []

    def replace(match):
        name = _field_name(match.group(1), fields)
        if name is None:
            unsupported.append(match.group(1).strip())
            return ""
        return "{{" + name + "}}"

    converted = _EXPRESSION_RE.sub(replace, text)
    if unsupported:
        return None, (
            "The map tip uses an expression the web app can't run "
            f"({unsupported[0]}): the attribute table is shown instead."
        )
    if len(converted) > MAX_TEMPLATE_CHARS:
        return None, "The map tip is too long for the web app: the attribute table is shown instead."
    return converted, None


def value_map_from_config(config):
    """``{stored value: label}`` from a QGIS ValueMap widget's config, or ``{}``.

    QGIS stores the map as a list of one-entry dicts ``[{"Label": "value"}, ...]``
    (older projects: a plain ``{"Label": "value"}``); the key is what people read, the
    value is what the layer stores.
    """
    entries = (config or {}).get("map") if isinstance(config, dict) else None
    pairs = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                pairs.extend(entry.items())
    elif isinstance(entries, dict):
        pairs.extend(entries.items())

    value_map = {}
    for label, value in pairs:
        if value is None or str(value) == "{2839923C-8B7D-417C-9D5C-0A3B6FA7F1F0}":  # QGIS's <NULL> marker
            continue
        value_map[str(value)] = str(label)
    return value_map


def field_widget_info(widget_type, config):
    """What a field's QGIS editor widget means for the popup: ``{"hidden": True}`` for a
    Hidden widget, ``{"valueMap": {...}}`` for a non-empty value map, else ``{}``."""
    if widget_type == WIDGET_HIDDEN:
        return {"hidden": True}
    if widget_type == WIDGET_VALUE_MAP:
        value_map = value_map_from_config(config)
        if value_map:
            return {"valueMap": value_map}
    return {}


def temporal_from_properties(active, mode_name, start_field, end_field, field_names):
    """The layer's QGIS temporal settings as the manifest's ``temporal`` entry, or ``None``.

    Only the modes that read the time from fields carry over (an instant in one field, or
    a start and an end field): the generated app filters by an attribute, so a layer whose
    time comes from a fixed range or an expression has nothing to filter on. ``mode_name``
    is the QGIS mode's name (``ModeFeatureDateTimeInstantFromField`` and so on).
    """
    if not active:
        return None
    mode = str(mode_name or "")
    fields = set(field_names)
    if "StartAndEndFromFields" in mode:
        if start_field in fields and end_field in fields:
            return {"startField": start_field, "endField": end_field}
        return None
    if "InstantFromField" in mode and start_field in fields:
        return {"startField": start_field}
    return None


def merge_field_info(*parts):
    """Combines per-field dicts (each ``{field: {...}}``): later parts add to, and win
    over, earlier ones. Fields left with nothing are dropped."""
    merged = {}
    for part in parts:
        for name, info in (part or {}).items():
            merged.setdefault(name, {}).update(info)
    return {name: info for name, info in merged.items() if info}
