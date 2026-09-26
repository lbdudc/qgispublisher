"""Get a layer's QGIS symbology into a shape QGIS's own SLD export (and GeoServer, which
draws the published layers) can carry.

``saveSldStyle`` gives up on some constructs (a heatmap, an inverted-polygon renderer, a
gradient fill, an ``ELSE`` rule nested in a filtered rule, a label expression) and silently
writes a generic fallback for others (point clusters). The published layer then loses its
style altogether. ``prepare_vector_layer`` works on a *copy* of the layer (the user's project
is never touched) and replaces each such construct with the closest thing SLD can express,
returning short notes about what had to be approximated so the run log can say so.

Only the small pure helpers at the top run without QGIS (``tests/test_style_prep.py``); the
rest is exercised against real QGIS layers.
"""

# Renderers SLD carries as they are
_EXPORTABLE_RENDERERS = frozenset({"singleSymbol", "categorizedSymbol", "graduatedSymbol", "RuleRenderer"})
# Wrappers that only decorate an embedded renderer: the embedded one is what gets drawn
_WRAPPER_RENDERERS = frozenset({"pointCluster", "pointDisplacement", "invertedPolygonRenderer", "mergedFeatureRenderer"})

# Symbol layers SLD carries (QGIS's exporter writes a real symbolizer for these)
_EXPORTABLE_SYMBOL_LAYERS = frozenset({
    "SimpleMarker", "SimpleLine", "MarkerLine",
    "SimpleFill", "LinePatternFill", "PointPatternFill", "CentroidFill",
})

NOTE_WRAPPER = "{kind} symbology is drawn as its plain symbols"
NOTE_HEATMAP = "the heatmap is drawn as semi-transparent points"
NOTE_UNKNOWN_RENDERER = "the {kind} renderer is drawn with a single default symbol"
NOTE_GRADIENT = "a gradient fill is drawn as a solid fill of its middle colour"
NOTE_SVG = "SVG symbols are drawn as plain shapes of the same colour (GeoServer cannot read the QGIS SVG library)"
NOTE_FONT = "font markers are drawn as plain marks (GeoServer does not have the QGIS fonts)"
NOTE_SYMBOL_LAYER = "a {kind} symbol layer is drawn as a plain symbol of the same colour"
NOTE_DATA_DEFINED = "data-defined symbol properties ({props}) are not published; the base symbol is used"
NOTE_LABEL_EXPRESSION = "the label expression could not be evaluated; the layer is published without labels"
NOTE_LABEL_KIND = "{kind} labelling is not supported; the layer is published without labels"
NOTE_LABEL_COMPUTED = (
    "the labels are computed by QGIS (the expression is evaluated for every feature) and published "
    "as the hidden column gp_label"
)
NOTE_LABEL_RULES = (
    "rule-based labels: the text of the first matching rule is published, all drawn with the style "
    "of the first rule (per-rule fonts, colours and scale ranges are not kept)"
)

# The hidden text column that carries computed label text to the generated app (a shapefile
# field name: at most 10 characters, lowercase, like the names the app gives its columns)
LABEL_FIELD = "gp_label"
LABEL_FIELD_LENGTH = 254


# Font characters people commonly use as map symbols -> the nearest simple marker shape
FONT_CHAR_SHAPES = {
    "★": "Star", "☆": "Star", "▲": "Triangle", "△": "Triangle", "■": "Square",
    "□": "Square", "◆": "Diamond", "♦": "Diamond", "✚": "Cross", "✖": "Cross2",
    "+": "Cross", "x": "Cross2", "X": "Cross2",
}


def quote_field(name):
    """A field name as it is written in a QGIS expression.

    >>> quote_field('name')
    '"name"'
    >>> quote_field('a"b')
    '"a""b"'
    """
    return '"' + name.replace('"', '""') + '"'


def label_case_expression(rules):
    """One expression for the text of a rule-based labelling: the text of the first rule
    whose filter holds. ``rules`` is ``[(filter, text_expression)]`` in the order QGIS
    draws them; a rule without a filter (or ``ELSE``) matches everything left, so the
    rules after it can never be reached. ``None`` for no rules.

    >>> label_case_expression([('"pop" > 100', '"name"'), ('', '"code"')])
    'CASE WHEN ("pop" > 100) THEN ("name") ELSE ("code") END'
    >>> label_case_expression([('', '"name"')])
    '"name"'
    >>> label_case_expression([]) is None
    True
    """
    branches = []
    fallback = None
    for flt, text in rules:
        flt = (flt or "").strip()
        if not flt or flt.upper() == "ELSE":
            fallback = text
            break
        branches.append(f"WHEN ({flt}) THEN ({text})")
    if not branches:
        return fallback
    tail = f" ELSE ({fallback})" if fallback else ""
    return "CASE " + " ".join(branches) + tail + " END"


def combine_filters(parent, child):
    """The filter of a nested rule: both its own and its parent's.

    >>> combine_filters('"a" = 1', '"b" = 2')
    '("a" = 1) AND ("b" = 2)'
    >>> combine_filters('', '"b" = 2')
    '"b" = 2'
    """
    parent, child = (parent or "").strip(), (child or "").strip()
    if parent and child:
        return f"({parent}) AND ({child})"
    return parent or child


def negated_siblings(filters):
    """The filter an ``ELSE`` rule stands for: none of the sibling filters holds.
    ``None`` when there is nothing to negate (an ELSE among unfiltered rules).

    >>> negated_siblings(['"a" = 1', '"b" > 2'])
    'NOT (("a" = 1) OR ("b" > 2))'
    """
    filters = [f.strip() for f in filters if f and f.strip() and f.strip().upper() != "ELSE"]
    if not filters:
        return None
    return "NOT (" + " OR ".join(f"({f})" for f in filters) + ")"


def mix_hex(color_a, color_b, weight=0.5):
    """Colour between two ``(r, g, b, a)`` tuples, as an ``(r, g, b, a)`` tuple."""
    return tuple(int(round(a + (b - a) * weight)) for a, b in zip(color_a, color_b))


# ------------------------------------------------------------------ QGIS-touching part

class LabelPlan:
    """What a layer's labels need that QGIS's SLD export cannot carry: the expression that
    gives each feature's label text (published as the ``gp_label`` column), the settings
    (font, halo, placement...) to draw it with, and notes for the run log."""

    def __init__(self, expression, settings, notes):
        self.expression = expression
        self.settings = settings
        self.notes = notes


def plan_labels(layer):
    """A `LabelPlan` when the layer's labels are an expression or rule-based, else ``None``
    (no labels, or plain field labels, which the SLD carries as they are). Never raises."""
    try:
        return _plan_labels(layer)
    except Exception:  # nosec B110 - labels are a nicety, the layer is published without them
        return None


def _text_expression(settings):
    return settings.fieldName if settings.isExpression else quote_field(settings.fieldName)


def _plan_labels(layer):
    from qgis.core import QgsExpression

    labeling = layer.labeling()
    if labeling is None or not layer.labelsEnabled():
        return None
    kind = labeling.type()

    if kind == "simple":
        settings = labeling.settings()
        if not settings.isExpression or not settings.fieldName:
            return None
        expr = QgsExpression(settings.fieldName)
        if expr.hasParserError() or expr.isField():
            return None  # a field written as an expression: reduced to the field, see _prepare_labeling
        return LabelPlan(settings.fieldName, settings, [NOTE_LABEL_COMPUTED])

    if kind == "rule-based":
        rules = []

        def walk(rule, inherited):
            flt = combine_filters(inherited, rule.filterExpression())
            settings = rule.settings()
            if settings is not None and rule.active() and settings.fieldName:
                rules.append((flt, _text_expression(settings), settings))
            for child in rule.children():
                if child.active():
                    walk(child, flt)

        walk(labeling.rootRule(), "")
        if not rules:
            return None
        expression = label_case_expression([(f, t) for f, t, _s in rules])
        if QgsExpression(expression).hasParserError():
            return None
        notes = [NOTE_LABEL_COMPUTED] + ([NOTE_LABEL_RULES] if len(rules) > 1 else [])
        return LabelPlan(expression, rules[0][2], notes)

    return None


def with_label_field(layer, plan):
    """A copy of ``layer`` with the labels' text as an extra (virtual) text field
    ``gp_label``: what gets exported and styled. The project's own layer is not touched.
    Returns ``layer`` itself, unchanged, if the field cannot be added."""
    from qgis.core import QgsField

    try:
        clone = layer.clone()
        if not clone.addExpressionField(plan.expression, QgsField(LABEL_FIELD, _string_type(), "", LABEL_FIELD_LENGTH)):
            return layer
        return clone
    except Exception:  # nosec B110 - the layer is then published without those labels
        return layer


def _string_type():
    """The 'text' field type in whatever form this QGIS/Qt takes it (Qt 5 and Qt 6)."""
    from qgis.PyQt.QtCore import QMetaType, QVariant

    try:
        return QMetaType.Type.QString
    except AttributeError:
        return QVariant.String


def prepare_vector_layer(layer, label_plan=None):
    """``(layer_to_export, notes)``: a copy of ``layer`` whose renderer/labelling SLD can
    carry, and what was approximated (each note is one sentence). Never raises: on any
    failure the original layer is returned so the old behaviour (whatever QGIS exports)
    stays the floor.

    ``label_plan`` (see `plan_labels`) says the labels are drawn from the ``gp_label``
    field of ``layer`` (which `with_label_field` added)."""
    notes = []
    try:
        clone = layer.clone()
        renderer = _prepare_renderer(clone, notes)
        if renderer is not None:
            clone.setRenderer(renderer)
        _prepare_labeling(clone, notes, label_plan)
        return clone, notes
    except Exception as e:  # nosec B110 - best-effort, see docstring
        return layer, [f"style preparation failed ({e}); QGIS's own export is used"]


def _prepare_renderer(layer, notes):
    from qgis.core import QgsSingleSymbolRenderer, QgsSymbol

    renderer = layer.renderer()
    if renderer is None:
        return None
    renderer = renderer.clone()

    for _ in range(6):  # wrappers can be nested (cluster around an inverted renderer...)
        kind = renderer.type()
        if kind in _WRAPPER_RENDERERS:
            embedded = renderer.embeddedRenderer()
            if embedded is None:
                break
            notes.append(NOTE_WRAPPER.format(kind=_pretty(kind)))
            renderer = embedded.clone()
        else:
            break

    kind = renderer.type()
    if kind == "heatmapRenderer":
        notes.append(NOTE_HEATMAP)
        renderer = QgsSingleSymbolRenderer(_heatmap_stand_in(layer, renderer))
    elif kind not in _EXPORTABLE_RENDERERS:
        notes.append(NOTE_UNKNOWN_RENDERER.format(kind=_pretty(kind)))
        renderer = QgsSingleSymbolRenderer(QgsSymbol.defaultSymbol(layer.geometryType()))
    elif kind == "RuleRenderer":
        _fix_else_rules(renderer.rootRule())

    _fix_symbols(renderer, notes)
    return renderer


def _pretty(kind):
    return {"pointCluster": "point-cluster", "pointDisplacement": "point-displacement",
            "invertedPolygonRenderer": "inverted-polygon", "mergedFeatureRenderer": "merged-features",
            "heatmapRenderer": "heatmap", "25dRenderer": "2.5D"}.get(kind, kind)


def _heatmap_stand_in(layer, heatmap):
    from qgis.core import QgsMarkerSymbol
    color = "#d7191c"
    try:
        ramp = heatmap.colorRamp()
        if ramp is not None:
            c = ramp.color(0.85)
            color = f"{c.red()},{c.green()},{c.blue()},110"
    except Exception:  # nosec B110 - the default colour is fine
        pass
    return QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "size": "4", "outline_style": "no"})


def _fix_else_rules(rule):
    """QGIS cannot export an ELSE rule that sits inside a filtered rule (its filter becomes
    ``<parent> AND ELSE``, a syntax error); spell the ELSE out as the negation of its
    siblings, which SLD carries. A top-level ELSE is exported as an ElseFilter, so it stays."""
    children = list(rule.children())
    if rule.parent() is not None:
        siblings = [c.filterExpression() for c in children if not c.isElse()]
        for child in children:
            if child.isElse():
                negated = negated_siblings(siblings)
                if negated:
                    child.setFilterExpression(negated)
    for child in children:
        _fix_else_rules(child)


def _fix_symbols(renderer, notes):
    from qgis.core import QgsRenderContext

    seen = set()
    for symbol in renderer.symbols(QgsRenderContext()):
        _fix_symbol(symbol, notes, seen)


def _fix_symbol(symbol, notes, seen):
    for i in range(symbol.symbolLayerCount()):
        sl = symbol.symbolLayer(i)
        kind = sl.layerType()
        props = _active_data_defined(sl)
        if props:
            _once(notes, seen, NOTE_DATA_DEFINED.format(props=", ".join(props)))
        if kind not in _EXPORTABLE_SYMBOL_LAYERS:
            replacement = _stand_in(symbol, sl, kind, notes, seen)
            if replacement is not None:
                symbol.changeSymbolLayer(i, replacement)
            continue
        sub = sl.subSymbol() if hasattr(sl, "subSymbol") else None
        if sub is not None:
            _fix_symbol(sub, notes, seen)


def _once(notes, seen, text):
    if text not in seen:
        seen.add(text)
        notes.append(text)


def _active_data_defined(symbol_layer):
    """Names of the symbol layer's expression-driven properties: the SLD exporter drops
    those (a size by field value, a colour by CASE...); a plain field rotation survives."""
    from qgis.core import QgsProperty, QgsSymbolLayer

    try:
        ddp = symbol_layer.dataDefinedProperties()
        if not ddp.hasActiveProperties():
            return []
        definitions = QgsSymbolLayer.propertyDefinitions()
        names = []
        for key in ddp.propertyKeys():
            prop = ddp.property(key)
            if prop.isActive() and prop.propertyType() == QgsProperty.ExpressionBasedProperty:
                definition = definitions.get(key)
                names.append(definition.name() if definition else str(key))
        return names
    except Exception:
        return []


def _stand_in(symbol, sl, kind, notes, seen):
    """A plain symbol layer of the same colour for one SLD cannot carry."""
    from qgis.core import Qgis, QgsSimpleFillSymbolLayer, QgsSimpleMarkerSymbolLayer, QgsSimpleLineSymbolLayer
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QColor

    geom = symbol.type()
    if kind == "GradientFill":
        _once(notes, seen, NOTE_GRADIENT)
        c1, c2 = sl.color(), sl.color2()
        mid = mix_hex((c1.red(), c1.green(), c1.blue(), c1.alpha()), (c2.red(), c2.green(), c2.blue(), c2.alpha()))
        fill = QgsSimpleFillSymbolLayer(QColor(*mid))
        fill.setStrokeStyle(Qt.NoPen)
        return fill
    if kind == "SvgMarker":
        _once(notes, seen, NOTE_SVG)
        square = "square" in (sl.path() or "").lower()
        marker = QgsSimpleMarkerSymbolLayer(
            QgsSimpleMarkerSymbolLayer.Square if square else QgsSimpleMarkerSymbolLayer.Circle,
            sl.size(), sl.angle(), Qgis.ScaleMethod.ScaleDiameter, sl.fillColor(), sl.strokeColor(),
        )
        marker.setSizeUnit(sl.sizeUnit())
        marker.setStrokeWidth(sl.strokeWidth())
        return marker
    if kind == "FontMarker":
        _once(notes, seen, NOTE_FONT)
        shape = FONT_CHAR_SHAPES.get(sl.character(), "Circle")
        return QgsSimpleMarkerSymbolLayer(
            getattr(QgsSimpleMarkerSymbolLayer, shape), sl.size(), sl.angle(),
            Qgis.ScaleMethod.ScaleDiameter, sl.color(), sl.strokeColor(),
        )
    if kind == "SVGFill":
        _once(notes, seen, NOTE_SVG)
        fill = QgsSimpleFillSymbolLayer(sl.svgFillColor())
        fill.setStrokeColor(sl.svgStrokeColor())
        fill.setStrokeWidth(sl.svgStrokeWidth())
        return fill
    _once(notes, seen, NOTE_SYMBOL_LAYER.format(kind=kind))
    color = sl.color()
    if geom == Qgis.SymbolType.Fill:
        fill = QgsSimpleFillSymbolLayer(color)
        fill.setStrokeColor(QColor("#232323"))
        return fill
    if geom == Qgis.SymbolType.Line:
        return QgsSimpleLineSymbolLayer(color, 0.6)
    return QgsSimpleMarkerSymbolLayer(QgsSimpleMarkerSymbolLayer.Circle, 3, 0, color)


def _prepare_labeling(layer, notes, label_plan=None):
    """Simple labels on a field export as a TextSymbolizer; an expression that is only a
    field is reduced to it. Labels that need computing (an expression, rules) are drawn
    from the ``gp_label`` field with the settings they had (``label_plan``); anything else
    is dropped."""
    from qgis.core import QgsExpression, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling

    labeling = layer.labeling()
    if labeling is None or not layer.labelsEnabled():
        return
    if label_plan is not None:
        settings = QgsPalLayerSettings(label_plan.settings)
        settings.fieldName = LABEL_FIELD
        settings.isExpression = False
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
        notes.extend(label_plan.notes)
        return
    kind = labeling.type()
    if kind != "simple":
        notes.append(NOTE_LABEL_KIND.format(kind=kind))
        layer.setLabeling(None)
        layer.setLabelsEnabled(False)
        return
    settings = labeling.settings()
    if settings.isExpression:
        expr = QgsExpression(settings.fieldName)
        if expr.hasParserError() or not expr.isField():
            notes.append(NOTE_LABEL_EXPRESSION)
            layer.setLabeling(None)
            layer.setLabelsEnabled(False)
            return
        settings.fieldName = expr.referencedColumns().pop() if expr.referencedColumns() else settings.fieldName
        settings.isExpression = False
        labeling.setSettings(settings)
