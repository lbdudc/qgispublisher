"""Build Vega v5 chart specs for the generated application's Chart Viewer, and
validate hand-authored or previously-generated chart JSON files.

Constraints these specs must honour (see the generator source under
``@lbdudc/gis-publisher`` / ``@lbdudc/mini-lps``):

- Charts placed in the selected "charts" folder are copied byte-for-byte into the
  generated app and read back with a plain ``JSON.parse`` — there is no template
  expansion, so a spec must be fully concrete (a real data URL, no ``__XFIELD__``-style
  placeholders) by the time it's written to disk.
- The "My charts" tab in the generated app's Chart Viewer does NOT substitute
  ``__XFIELD__``/``__YFIELD__``/``__ENTITY__`` — those are only expanded for the
  built-in Explorer templates. A saved chart with leftover placeholders renders with
  literal ``"null"`` values.
- Data is fetched from ``{base_url}/api/entities/{entity_url_segment}/export/tsv``
  as a Vega ``"format": {"type": "tsv", "parse": "auto"}`` data source.
"""

import json
import re

from . import naming

VEGA_SCHEMA = "https://vega.github.io/schema/vega/v5.json"

CHART_TYPE_BAR = "bar"
CHART_TYPE_LINE = "line"
CHART_TYPE_PIE = "pie"
CHART_TYPE_DONUT = "donut"
CHART_TYPE_GROUPED_BAR = "grouped_bar"
CHART_TYPE_STACKED_BAR = "stacked_bar"
CHART_TYPE_AREA = "area"
CHART_TYPE_SCATTER = "scatter"
CHART_TYPE_HISTOGRAM = "histogram"
CHART_TYPE_BOX_PLOT = "box_plot"
CHART_TYPE_HEATMAP = "heatmap"

CHART_TYPE_LABELS = {
    CHART_TYPE_BAR: "Bar chart",
    CHART_TYPE_LINE: "Line chart",
    CHART_TYPE_PIE: "Pie chart",
    CHART_TYPE_DONUT: "Donut chart",
    CHART_TYPE_GROUPED_BAR: "Grouped bar chart",
    CHART_TYPE_STACKED_BAR: "Stacked bar chart",
    CHART_TYPE_AREA: "Area chart",
    CHART_TYPE_SCATTER: "Scatter plot",
    CHART_TYPE_HISTOGRAM: "Histogram",
    CHART_TYPE_BOX_PLOT: "Box plot",
    CHART_TYPE_HEATMAP: "Heatmap",
}

_AUTOSIZE = {"type": "fit", "contains": "padding"}
_WIDTH_SIGNAL = {"signal": "max(800, length(data('dataset')) * 30)"}
_TOOLTIP = {"signal": "datum"}


def data_url(base_url, layer_basename):
    base = (base_url or "http://localhost:8080").rstrip("/")
    return f"{base}/api/entities/{naming.entity_url_segment(layer_basename)}/export/tsv"


def _tsv_data_source(base_url, layer_basename, transform=None):
    source = {
        "name": "dataset",
        "url": data_url(base_url, layer_basename),
        "format": {"type": "tsv", "parse": "auto"},
    }
    if transform:
        source["transform"] = transform
    return source


def _base_spec(description, data_sources):
    return {
        "$schema": VEGA_SCHEMA,
        "description": description,
        "width": _WIDTH_SIGNAL,
        "height": 400,
        "padding": 5,
        "autosize": _AUTOSIZE,
        "data": data_sources,
    }


def build_chart_spec(chart_type, layer_basename, base_url, x_field, y_field=None, color_field=None):
    """Build a concrete Vega v5 spec for chart_type against layer_basename's entity.

    x_field/y_field/color_field are raw QGIS field names — this maps each one through
    naming.attribute_name itself, so callers should pass the field name as QGIS shows
    it, not a pre-mapped attribute name.
    """
    x = naming.attribute_name(x_field) if x_field else x_field
    y = naming.attribute_name(y_field) if y_field else y_field
    color = naming.attribute_name(color_field) if color_field else color_field

    builder = _BUILDERS.get(chart_type)
    if builder is None:
        raise ValueError(f"Unknown chart type: {chart_type}")
    return builder(layer_basename, base_url, x, y, color)


def _build_bar(layer_basename, base_url, x, y, color):
    spec = _base_spec(
        f"Bar chart for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename)],
    )
    spec["scales"] = [
        {"name": "x", "type": "band", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.1},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "field": y}, "range": "height", "nice": True, "zero": True},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "labelAngle": -45},
        {"orient": "left", "scale": "y", "title": y, "grid": True},
    ]
    spec["marks"] = [{
        "type": "rect",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "x": {"scale": "x", "field": x},
            "width": {"scale": "x", "band": 1},
            "y": {"scale": "y", "field": y},
            "y2": {"scale": "y", "value": 0},
            "fill": {"value": "steelblue"},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


def _build_line(layer_basename, base_url, x, y, color):
    transform = [
        {"type": "filter", "expr": f"datum['{x}'] != null && datum['{y}'] != null"},
        {"type": "collect", "sort": {"field": x, "order": "ascending"}},
    ]
    spec = _base_spec(
        f"Line chart for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [
        {"name": "x", "type": "point", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.5},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "field": y}, "range": "height", "nice": True, "zero": True},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "labelAngle": -45, "labelAlign": "right", "labelOverlap": "parity", "labelFontSize": 10, "tickCount": 20},
        {"orient": "left", "scale": "y", "title": y, "format": "~s", "grid": True, "gridOpacity": 0.1},
    ]
    spec["marks"] = [
        {
            "type": "line",
            "from": {"data": "dataset"},
            "encode": {"update": {
                "x": {"scale": "x", "field": x},
                "y": {"scale": "y", "field": y},
                "stroke": {"value": "steelblue"},
                "strokeWidth": {"value": 2},
                "strokeOpacity": {"value": 0.8},
            }},
        },
        {
            "type": "symbol",
            "from": {"data": "dataset"},
            "encode": {"update": {
                "x": {"scale": "x", "field": x},
                "y": {"scale": "y", "field": y},
                "fill": {"value": "white"},
                "stroke": {"value": "steelblue"},
                "strokeWidth": {"value": 1},
                "size": {"value": 30},
                "tooltip": _TOOLTIP,
            }},
        },
    ]
    return spec


def _build_pie(layer_basename, base_url, x, y, color, inner_radius=0):
    transform = [
        {"type": "aggregate", "groupby": [x], "fields": [y], "ops": ["sum"], "as": [y]},
        {"type": "pie", "field": y},
    ]
    spec = _base_spec(
        f"Pie chart for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [{"name": "color", "type": "ordinal", "domain": {"data": "dataset", "field": x}, "range": {"scheme": "category10"}}]
    spec["legends"] = [{"fill": "color", "title": x}]
    spec["marks"] = [{
        "type": "arc",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "fill": {"scale": "color", "field": x},
            "x": {"signal": "width / 2"},
            "y": {"signal": "height / 2"},
            "startAngle": {"field": "startAngle"},
            "endAngle": {"field": "endAngle"},
            "innerRadius": {"value": inner_radius},
            "outerRadius": {"signal": "min(width, height) / 2"},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


def _build_donut(layer_basename, base_url, x, y, color):
    return _build_pie(layer_basename, base_url, x, y, color, inner_radius=60)


def _build_grouped_bar(layer_basename, base_url, x, y, color):
    group_field = color or x
    spec = _base_spec(
        f"Grouped bar chart for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename)],
    )
    spec["scales"] = [
        {"name": "xgroup", "type": "band", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.2},
        {"name": "xsub", "type": "band", "domain": {"data": "dataset", "field": group_field}, "range": {"signal": "[0, xgroup_bandwidth]"}, "padding": 0.1},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "field": y}, "range": "height", "nice": True, "zero": True},
        {"name": "color", "type": "ordinal", "domain": {"data": "dataset", "field": group_field}, "range": {"scheme": "category10"}},
    ]
    spec["signals"] = [{"name": "xgroup_bandwidth", "update": "bandwidth('xgroup')"}]
    spec["axes"] = [
        {"orient": "bottom", "scale": "xgroup", "title": x, "labelAngle": -45},
        {"orient": "left", "scale": "y", "title": y, "grid": True},
    ]
    spec["legends"] = [{"fill": "color", "title": group_field}]
    spec["marks"] = [{
        "type": "group",
        "from": {"facet": {"data": "dataset", "name": "facet", "groupby": [x]}},
        "encode": {"enter": {"x": {"scale": "xgroup", "field": x}}},
        "signals": [{"name": "width", "update": "xgroup_bandwidth"}],
        "scales": [{"name": "pos", "type": "band", "range": "width", "domain": {"data": "facet", "field": group_field}}],
        "marks": [{
            "type": "rect",
            "from": {"data": "facet"},
            "encode": {"update": {
                "x": {"scale": "pos", "field": group_field},
                "width": {"scale": "pos", "band": 1},
                "y": {"scale": "y", "field": y},
                "y2": {"scale": "y", "value": 0},
                "fill": {"scale": "color", "field": group_field},
                "tooltip": _TOOLTIP,
            }},
        }],
    }]
    return spec


def _build_stacked_bar(layer_basename, base_url, x, y, color):
    stack_field = color or x
    transform = [{"type": "stack", "groupby": [x], "field": y, "sort": {"field": stack_field}, "as": ["y0", "y1"]}]
    spec = _base_spec(
        f"Stacked bar chart for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [
        {"name": "x", "type": "band", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.1},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "fields": ["y0", "y1"]}, "range": "height", "nice": True, "zero": True},
        {"name": "color", "type": "ordinal", "domain": {"data": "dataset", "field": stack_field}, "range": {"scheme": "category10"}},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "labelAngle": -45},
        {"orient": "left", "scale": "y", "title": y, "grid": True},
    ]
    spec["legends"] = [{"fill": "color", "title": stack_field}]
    spec["marks"] = [{
        "type": "rect",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "x": {"scale": "x", "field": x},
            "width": {"scale": "x", "band": 1},
            "y": {"scale": "y", "field": "y0"},
            "y2": {"scale": "y", "field": "y1"},
            "fill": {"scale": "color", "field": stack_field},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


def _build_area(layer_basename, base_url, x, y, color):
    transform = [
        {"type": "filter", "expr": f"datum['{x}'] != null && datum['{y}'] != null"},
        {"type": "collect", "sort": {"field": x, "order": "ascending"}},
    ]
    spec = _base_spec(
        f"Area chart for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [
        {"name": "x", "type": "point", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.5},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "field": y}, "range": "height", "nice": True, "zero": True},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "labelAngle": -45},
        {"orient": "left", "scale": "y", "title": y, "grid": True},
    ]
    spec["marks"] = [{
        "type": "area",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "x": {"scale": "x", "field": x},
            "y": {"scale": "y", "field": y},
            "y2": {"scale": "y", "value": 0},
            "fill": {"value": "steelblue"},
            "fillOpacity": {"value": 0.6},
            "stroke": {"value": "steelblue"},
            "strokeWidth": {"value": 2},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


def _build_scatter(layer_basename, base_url, x, y, color):
    spec = _base_spec(
        f"Scatter plot for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename)],
    )
    spec["scales"] = [
        {"name": "x", "type": "linear", "domain": {"data": "dataset", "field": x}, "range": "width", "nice": True, "zero": False},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "field": y}, "range": "height", "nice": True, "zero": False},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "grid": True},
        {"orient": "left", "scale": "y", "title": y, "grid": True},
    ]
    fill = {"value": "steelblue"}
    if color:
        spec["scales"].append({"name": "color", "type": "ordinal", "domain": {"data": "dataset", "field": color}, "range": {"scheme": "category10"}})
        spec["legends"] = [{"fill": "color", "title": color}]
        fill = {"scale": "color", "field": color}
    spec["marks"] = [{
        "type": "symbol",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "x": {"scale": "x", "field": x},
            "y": {"scale": "y", "field": y},
            "size": {"value": 60},
            "fill": fill,
            "fillOpacity": {"value": 0.7},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


def _build_histogram(layer_basename, base_url, x, y, color):
    field = x
    transform = [
        {"type": "bin", "field": field, "as": ["bin0", "bin1"]},
        {"type": "aggregate", "groupby": ["bin0", "bin1"], "ops": ["count"], "as": ["count"]},
    ]
    spec = _base_spec(
        f"Histogram for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [
        {"name": "x", "type": "linear", "domain": {"data": "dataset", "fields": ["bin0", "bin1"]}, "range": "width", "nice": True, "zero": False},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "field": "count"}, "range": "height", "nice": True, "zero": True},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": field, "grid": False},
        {"orient": "left", "scale": "y", "title": "Count", "grid": True},
    ]
    spec["marks"] = [{
        "type": "rect",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "x": {"scale": "x", "field": "bin0"},
            "x2": {"scale": "x", "field": "bin1"},
            "y": {"scale": "y", "field": "count"},
            "y2": {"scale": "y", "value": 0},
            "fill": {"value": "steelblue"},
            "fillOpacity": {"value": 0.8},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


def _build_box_plot(layer_basename, base_url, x, y, color):
    transform = [{
        "type": "aggregate",
        "groupby": [x],
        "fields": [y, y, y],
        "ops": ["q1", "median", "q3"],
        "as": ["q1", "median", "q3"],
    }]
    spec = _base_spec(
        f"Box plot for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [
        {"name": "x", "type": "band", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.3},
        {"name": "y", "type": "linear", "domain": {"data": "dataset", "fields": ["q1", "q3"]}, "range": "height", "nice": True, "zero": False},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "labelAngle": -45},
        {"orient": "left", "scale": "y", "title": y, "grid": True},
    ]
    spec["marks"] = [
        {
            "type": "rule",
            "from": {"data": "dataset"},
            "encode": {"update": {
                "x": {"scale": "x", "field": x, "band": 0.5},
                "y": {"scale": "y", "field": "q1"},
                "y2": {"scale": "y", "field": "q3"},
                "stroke": {"value": "steelblue"},
                "strokeWidth": {"value": 1.5},
            }},
        },
        {
            "type": "rect",
            "from": {"data": "dataset"},
            "encode": {"update": {
                "x": {"scale": "x", "field": x},
                "width": {"scale": "x", "band": 0.6},
                "y": {"scale": "y", "field": "median", "offset": -2},
                "height": {"value": 4},
                "fill": {"value": "steelblue"},
                "tooltip": _TOOLTIP,
            }},
        },
    ]
    return spec


def _build_heatmap(layer_basename, base_url, x, y, color):
    measure = color or y
    transform = [{"type": "aggregate", "groupby": [x, y], "fields": [measure], "ops": ["mean"], "as": ["value"]}]
    spec = _base_spec(
        f"Heatmap for {layer_basename}",
        [_tsv_data_source(base_url, layer_basename, transform)],
    )
    spec["scales"] = [
        {"name": "x", "type": "band", "domain": {"data": "dataset", "field": x}, "range": "width", "padding": 0.05},
        {"name": "y", "type": "band", "domain": {"data": "dataset", "field": y}, "range": "height", "padding": 0.05},
        {"name": "color", "type": "linear", "domain": {"data": "dataset", "field": "value"}, "range": {"scheme": "yellowgreenblue"}, "zero": True, "nice": True},
    ]
    spec["axes"] = [
        {"orient": "bottom", "scale": "x", "title": x, "labelAngle": -45},
        {"orient": "left", "scale": "y", "title": y},
    ]
    spec["legends"] = [{"fill": "color", "title": "Value", "type": "gradient"}]
    spec["marks"] = [{
        "type": "rect",
        "from": {"data": "dataset"},
        "encode": {"update": {
            "x": {"scale": "x", "field": x},
            "width": {"scale": "x", "band": 1},
            "y": {"scale": "y", "field": y},
            "height": {"scale": "y", "band": 1},
            "fill": {"scale": "color", "field": "value"},
            "tooltip": _TOOLTIP,
        }},
    }]
    return spec


_BUILDERS = {
    CHART_TYPE_BAR: _build_bar,
    CHART_TYPE_LINE: _build_line,
    CHART_TYPE_PIE: _build_pie,
    CHART_TYPE_DONUT: _build_donut,
    CHART_TYPE_GROUPED_BAR: _build_grouped_bar,
    CHART_TYPE_STACKED_BAR: _build_stacked_bar,
    CHART_TYPE_AREA: _build_area,
    CHART_TYPE_SCATTER: _build_scatter,
    CHART_TYPE_HISTOGRAM: _build_histogram,
    CHART_TYPE_BOX_PLOT: _build_box_plot,
    CHART_TYPE_HEATMAP: _build_heatmap,
}

# Fields required from the caller for each chart type: (needs_x, needs_y, needs_color)
CHART_TYPE_FIELD_REQUIREMENTS = {
    CHART_TYPE_BAR: (True, True, False),
    CHART_TYPE_LINE: (True, True, False),
    CHART_TYPE_PIE: (True, True, False),
    CHART_TYPE_DONUT: (True, True, False),
    CHART_TYPE_GROUPED_BAR: (True, True, True),
    CHART_TYPE_STACKED_BAR: (True, True, True),
    CHART_TYPE_AREA: (True, True, False),
    CHART_TYPE_SCATTER: (True, True, False),
    CHART_TYPE_HISTOGRAM: (True, False, False),
    CHART_TYPE_BOX_PLOT: (True, True, False),
    CHART_TYPE_HEATMAP: (True, True, False),
}


def inline_preview_spec(spec, rows, max_rows=2000):
    """Return a copy of `spec` with its first data source's `url`/`format` swapped
    for an inline `values` array, so it can be rendered offline against the layer's
    real attribute data (for the in-plugin preview) without a running backend.

    `rows` is a list of dicts (already using the same attribute names the spec's
    transforms/encodings reference).
    """
    preview = json.loads(json.dumps(spec))  # deep copy
    data_sources = preview.get("data") or []
    if not data_sources:
        return preview
    dataset = data_sources[0]
    dataset.pop("url", None)
    dataset.pop("format", None)
    dataset["values"] = rows[:max_rows]
    return preview


# ----------------------------------------------------------------------
# Validation of chart spec files
# ----------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"__[A-Z]+__")
_ENTITY_URL_RE = re.compile(r"/api/entities/([^/\"']+)/")


def _collect_field_refs(node, out):
    """Recursively collect every string value assigned to a `"field"` key."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "field" and isinstance(value, str):
                out.add(value)
            elif key == "fields" and isinstance(value, list):
                out.update(v for v in value if isinstance(v, str))
            else:
                _collect_field_refs(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_field_refs(item, out)


def validate_chart_spec(raw_text, selected_layer_basenames, layer_fields_by_basename=None):
    """Validate a chart spec's text content. Returns a list of human-readable issue
    strings; an empty list means the spec looks usable.

    `selected_layer_basenames` is the list of layer file basenames currently checked
    in the plugin, used to cross-check the spec's entity URL and field names. Passing
    an empty list skips those two checks (only JSON/schema/placeholder checks run).

    `layer_fields_by_basename`, if given, maps a layer basename to the set of its
    attribute names (already run through naming.attribute_name) — when the spec's
    data URL matches one of those layers, every `"field"`/`"fields"` reference in the
    spec is checked against that set.
    """
    issues = []

    try:
        spec = json.loads(raw_text)
    except ValueError as e:
        return [f"Not valid JSON: {e}"]

    schema = spec.get("$schema", "")
    if "vega-lite" in schema:
        pass  # Vega-Lite v5 is valid too, just not what the app's own templates use.
    elif "vega" in schema and "v5" in schema:
        pass
    elif "vega" in schema:
        issues.append(f"Schema '{schema}' is not Vega v5 — the generated app bundles Vega 5.22 / Vega-Lite 5.2.")
    else:
        issues.append("Missing or unrecognized $schema — expected a Vega or Vega-Lite v5 schema URL.")

    if _PLACEHOLDER_RE.search(raw_text):
        issues.append(
            "Contains __PLACEHOLDER__-style tokens (e.g. __XFIELD__/__YFIELD__/__ENTITY__) — "
            "these are only expanded for the app's built-in chart templates, not for saved charts, "
            "and will render as the literal value \"null\"."
        )

    data_sources = spec.get("data") or []
    url = ""
    if data_sources and isinstance(data_sources[0], dict):
        url = data_sources[0].get("url", "") or ""

    matched_basename = None
    if selected_layer_basenames:
        if not url:
            issues.append("No data URL found in the first data source — chart will have no data.")
        else:
            m = _ENTITY_URL_RE.search(url)
            if not m:
                issues.append(f"Data URL doesn't look like an entity export endpoint: {url}")
            else:
                entity_segment = m.group(1)
                for basename in selected_layer_basenames:
                    if naming.entity_url_segment(basename) == entity_segment:
                        matched_basename = basename
                        break
                if matched_basename is None:
                    expected = ", ".join(sorted(naming.entity_url_segment(b) for b in selected_layer_basenames))
                    issues.append(
                        f"URL entity segment '{entity_segment}' doesn't match any selected layer "
                        f"(expected one of: {expected})."
                    )

    if matched_basename is not None and layer_fields_by_basename:
        known_fields = layer_fields_by_basename.get(matched_basename)
        if known_fields is not None:
            # "id" is always present (the entity's identifier field), regardless of
            # the source layer's attribute table.
            known_fields = known_fields | {"id", "id2"}
            referenced = set()
            _collect_field_refs(spec, referenced)
            unknown = sorted(f for f in referenced if f not in known_fields)
            if unknown:
                issues.append(
                    f"References field(s) not found on layer '{matched_basename}': {', '.join(unknown)}."
                )

    return issues
