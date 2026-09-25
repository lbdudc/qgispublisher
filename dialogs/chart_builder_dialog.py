import json
import logging
import os
import re
import tempfile

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QUrl, QVariant
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.core import NULL

from ..core import chart_builder, chart_preview, naming

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "chart_builder_dialog.ui")
)

_LOGGER = logging.getLogger(__name__)

_NUMERIC_TYPES = {
    QVariant.Int,
    QVariant.UInt,
    QVariant.LongLong,
    QVariant.ULongLong,
    QVariant.Double,
}

_PREVIEW_MAX_ROWS = 2000

try:
    from qgis.PyQt.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE_AVAILABLE = True
except ImportError:  # QtWebEngine isn't bundled with every QGIS install/platform
    QWebEngineView = None
    _WEBENGINE_AVAILABLE = False

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


class ChartBuilderDialog(QDialog, FORM_CLASS):
    """Build a Vega chart spec from a layer's fields, with a live preview against
    the layer's real attribute data, and save it into the plugin's chart folder."""

    def __init__(self, layers, default_base_url, chart_folder, existing_names, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.layers = layers
        # Single authority for "what basename will this layer be staged under" (see
        # naming.assign_staged_basenames) — computed once, over the same layer list
        # and order the main dialog uses for validation/staging, so a chart built here
        # always predicts the same entity the generator will actually expose.
        self._basename_by_id = naming.assign_staged_basenames(
            (layer.id(), naming.layer_source_basename(layer)) for layer in layers
        )
        self.chart_folder = chart_folder
        self.existing_names = set(existing_names or [])
        self.saved_chart_filename = None
        self.saved_chart_folder = None

        self._web_view = None
        if _WEBENGINE_AVAILABLE:
            self._web_view = QWebEngineView(self.previewPanel)
            self.previewPanelLayout.insertWidget(0, self._web_view)
        else:
            self.previewFallbackLabel.setVisible(True)

        self.baseUrlEdit.setText(default_base_url or "/backend")

        for layer in self.layers:
            self.layerCombo.addItem(layer.name(), layer.id())

        for chart_type, label in chart_builder.CHART_TYPE_LABELS.items():
            self.chartTypeCombo.addItem(label, chart_type)

        self.layerCombo.currentIndexChanged.connect(self._on_layer_changed)
        self.chartTypeCombo.currentIndexChanged.connect(self._on_chart_type_changed)
        self.xFieldCombo.currentIndexChanged.connect(self._refresh_preview)
        self.yFieldCombo.currentIndexChanged.connect(self._refresh_preview)
        self.colorFieldCombo.currentIndexChanged.connect(self._refresh_preview)
        self.baseUrlEdit.textChanged.connect(self._refresh_preview)
        self.previewBrowserButton.clicked.connect(self._open_preview_in_browser)
        self.saveButton.clicked.connect(self._on_save)
        self.cancelButton.clicked.connect(self.reject)

        self._on_layer_changed()

    # ------------------------------------------------------------------

    def _current_layer(self):
        idx = self.layerCombo.currentIndex()
        if idx < 0 or idx >= len(self.layers):
            return None
        return self.layers[idx]

    def _layer_basename(self, layer):
        return self._basename_by_id.get(layer.id(), naming.layer_source_basename(layer))

    def _numeric_fields(self, layer):
        return [f.name() for f in layer.fields() if f.type() in _NUMERIC_TYPES]

    def _all_fields(self, layer):
        return [f.name() for f in layer.fields()]

    def _field_types(self, layer):
        """{field_name: "numeric"|"categorical"}, passed to
        chart_builder.build_chart_spec so the scatter plot can pick a linear vs.
        point scale per axis instead of assuming every field is numeric."""
        numeric = set(self._numeric_fields(layer))
        return {name: ("numeric" if name in numeric else "categorical") for name in self._all_fields(layer)}

    def _on_layer_changed(self):
        layer = self._current_layer()
        if layer is None:
            return
        self._populate_field_combos(layer)
        self._refresh_preview()

    def _on_chart_type_changed(self):
        layer = self._current_layer()
        if layer is None:
            return
        self._populate_field_combos(layer)
        self._refresh_preview()

    def _populate_field_combos(self, layer):
        chart_type = self.chartTypeCombo.currentData()
        needs_x, needs_y, needs_color = chart_builder.CHART_TYPE_FIELD_REQUIREMENTS.get(
            chart_type, (True, True, False)
        )

        all_fields = self._all_fields(layer)
        numeric_fields = self._numeric_fields(layer)

        is_histogram = chart_type == chart_builder.CHART_TYPE_HISTOGRAM
        is_measure_y = chart_type not in (
            chart_builder.CHART_TYPE_SCATTER,
            chart_builder.CHART_TYPE_HEATMAP,
            chart_builder.CHART_TYPE_BOX_PLOT,
        )

        self.xFieldLabel.setText("Field" if is_histogram else "Category")
        self.xFieldCombo.blockSignals(True)
        self.xFieldCombo.clear()
        x_choices = numeric_fields if is_histogram else all_fields
        self.xFieldCombo.addItems(x_choices)
        self.xFieldCombo.blockSignals(False)
        self.xFieldCombo.setEnabled(needs_x and bool(x_choices))

        self.yFieldLabel.setVisible(needs_y)
        self.yFieldCombo.setVisible(needs_y)
        self.yFieldLabel.setText("Value" if is_measure_y else "Y field")
        if needs_y:
            self.yFieldCombo.blockSignals(True)
            self.yFieldCombo.clear()
            y_choices = numeric_fields if is_measure_y else all_fields
            self.yFieldCombo.addItems(y_choices)
            self.yFieldCombo.blockSignals(False)
            self.yFieldCombo.setEnabled(bool(y_choices))

        color_is_optional = chart_type in chart_builder.CHART_TYPES_WITH_OPTIONAL_COLOR
        show_color = needs_color or color_is_optional
        self.colorFieldLabel.setVisible(show_color)
        self.colorFieldCombo.setVisible(show_color)
        self.colorFieldLabel.setText("Group by" if needs_color else "Color by (optional)")
        if show_color:
            self.colorFieldCombo.blockSignals(True)
            self.colorFieldCombo.clear()
            if color_is_optional and not needs_color:
                self.colorFieldCombo.addItem("(none)", None)
            self.colorFieldCombo.addItems(all_fields)
            self.colorFieldCombo.blockSignals(False)

        if not self.chartNameEdit.text().strip():
            basename = self._layer_basename(layer)
            self.chartNameEdit.setPlaceholderText(f"{basename}_{chart_type}")

    # ------------------------------------------------------------------

    def _resolved_data_url(self, layer):
        return chart_builder.data_url(self.baseUrlEdit.text(), self._layer_basename(layer))

    def _build_current_spec(self, layer):
        chart_type = self.chartTypeCombo.currentData()
        x_field = self.xFieldCombo.currentText() or None
        y_field = self.yFieldCombo.currentText() if self.yFieldCombo.isVisible() else None
        # Only the scatter plot's "(none)" placeholder item carries explicit
        # userData (None); every real field name comes from a plain addItems()
        # call, so its userData is None too and the field name itself (currentText)
        # is what we actually want.
        color_field = None
        if self.colorFieldCombo.isVisible() and self.colorFieldCombo.currentText() not in ("", "(none)"):
            color_field = self.colorFieldCombo.currentText()

        return chart_builder.build_chart_spec(
            chart_type,
            self._layer_basename(layer),
            self.baseUrlEdit.text(),
            x_field,
            y_field,
            color_field,
            field_types=self._field_types(layer),
        )

    def _fetch_preview_rows(self, layer):
        rows = []
        field_names = [f.name() for f in layer.fields()]
        try:
            for i, feature in enumerate(layer.getFeatures()):
                if i >= _PREVIEW_MAX_ROWS:
                    break
                row = {}
                for name in field_names:
                    value = feature[name]
                    row[naming.entity_property_name(name)] = _json_safe(value)
                rows.append(row)
        except Exception:
            _LOGGER.exception("Failed to build chart preview rows")
        return rows

    def _refresh_preview(self):
        layer = self._current_layer()
        if layer is None:
            return

        url_text = f"Data URL: {self._resolved_data_url(layer)}"
        total_features = layer.featureCount()
        if total_features > _PREVIEW_MAX_ROWS:
            url_text += f"  ·  preview showing first {_PREVIEW_MAX_ROWS:,} of {total_features:,} features"
        self.resolvedUrlLabel.setText(url_text)

        try:
            spec = self._build_current_spec(layer)
        except Exception as e:
            self.validationLabel.setText(f"Could not build chart: {e}")
            return

        known_attrs = {naming.entity_property_name(name) for name in self._all_fields(layer)}
        issues = chart_builder.validate_chart_spec(
            json.dumps(spec),
            [self._layer_basename(layer)],
            {self._layer_basename(layer): known_attrs},
        )
        self.validationLabel.setText("\n".join(issues))

        rows = self._fetch_preview_rows(layer)
        preview_spec = chart_builder.inline_preview_spec(spec, rows)
        self._render_preview(preview_spec)

    def _render_preview(self, spec):
        if self._web_view is None:
            return
        html_path = os.path.join(tempfile.gettempdir(), "qgis_gispublisher_chart_preview.html")
        try:
            chart_preview.write_preview_html(spec, html_path)
            self._web_view.load(QUrl.fromLocalFile(html_path))
        except Exception as e:
            self.validationLabel.setText(f"Preview error: {e}")

    def _open_preview_in_browser(self):
        layer = self._current_layer()
        if layer is None:
            return
        try:
            spec = self._build_current_spec(layer)
            rows = self._fetch_preview_rows(layer)
            preview_spec = chart_builder.inline_preview_spec(spec, rows)
            html_path = os.path.join(tempfile.gettempdir(), "qgis_gispublisher_chart_preview.html")
            chart_preview.write_preview_html(preview_spec, html_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(html_path))
        except Exception as e:
            QMessageBox.critical(self, "Preview error", str(e))

    # ------------------------------------------------------------------

    def _on_save(self):
        layer = self._current_layer()
        if layer is None:
            QMessageBox.warning(self, "No layer", "Select a layer first.")
            return

        try:
            spec = self._build_current_spec(layer)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not build chart: {e}")
            return

        name = self.chartNameEdit.text().strip() or self.chartNameEdit.placeholderText()
        name = _INVALID_FILENAME_CHARS.sub("_", name)
        if not name:
            QMessageBox.warning(self, "Name required", "Give the chart a name before saving.")
            return

        if name in self.existing_names:
            reply = QMessageBox.question(
                self,
                "Overwrite chart?",
                f'A chart named "{name}" already exists. Overwrite it?',
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        dest_folder = self.chart_folder or _default_chart_folder()
        try:
            os.makedirs(dest_folder, exist_ok=True)
            dest_path = os.path.join(dest_folder, f"{name}.json")
            with open(dest_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not save chart: {e}")
            return

        self.saved_chart_folder = dest_folder
        self.saved_chart_filename = f"{name}.json"
        self.accept()


def _default_chart_folder():
    """Plugin-managed folder used when the user hasn't picked a charts folder yet."""
    from qgis.core import QgsApplication

    settings_dir = QgsApplication.qgisSettingsDirPath()
    folder = os.path.join(settings_dir, "GISPublisher", "charts")
    os.makedirs(folder, exist_ok=True)
    return folder


def _json_safe(value):
    """Coerce a QGIS attribute value into something json.dumps can handle."""
    if value is None or value == NULL:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    # QDate/QDateTime/QTime and similar expose isoformat-style toString via str().
    try:
        return str(value)
    except Exception:
        return None
