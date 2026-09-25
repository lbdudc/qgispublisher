from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import web_options


class WebOptionsGroup(QGroupBox):
    """The "Web app" box of the main dialog: how the generated app looks (title, logo,
    colour, basemap) and which extras it has (map search, legend, downloads).

    Builds no data itself: ``settings()`` is what ``core.web_options`` turns into the
    manifest, and ``set_settings`` takes the same shape back (a project's saved choice).
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Web app", parent)
        self.setObjectName("webOptionsGroup")
        self.setToolTip("How the generated web app looks and what it offers.")

        self.titleEdit = QLineEdit()
        self.titleEdit.setObjectName("brandingTitleEdit")
        self.titleEdit.setToolTip("The name shown in the app's title bar and browser tab.")

        self.logoEdit = QLineEdit()
        self.logoEdit.setObjectName("brandingLogoEdit")
        self.logoEdit.setReadOnly(True)
        self.logoEdit.setPlaceholderText("No logo")
        self.logoButton = QPushButton("Choose…")
        self.logoButton.setObjectName("brandingLogoButton")
        self.logoClearButton = QPushButton("Clear")
        self.logoClearButton.setObjectName("brandingLogoClearButton")

        self.colorEdit = QLineEdit()
        self.colorEdit.setObjectName("brandingColorEdit")
        self.colorEdit.setPlaceholderText("#1976d2")
        self.colorEdit.setMaximumWidth(110)
        self.colorEdit.setToolTip("The app's main colour, as #rrggbb. Empty keeps the default blue.")
        self.colorButton = QPushButton("Pick…")
        self.colorButton.setObjectName("brandingColorButton")

        self.basemapCombo = QComboBox()
        self.basemapCombo.setObjectName("brandingBasemapCombo")
        for basemap_id, label in web_options.BASEMAPS.items():
            self.basemapCombo.addItem(label, basemap_id)
        self.basemapCombo.setToolTip("The map the layers are drawn over.")

        self.searchCheck = QCheckBox("Search box on the map")
        self.searchCheck.setObjectName("optionSearchCheck")
        self.searchCheck.setToolTip("Find features by any text in them, and zoom to the result.")
        self.geocoderCheck = QCheckBox("Address and place search")
        self.geocoderCheck.setObjectName("optionGeocoderCheck")
        self.geocoderCheck.setToolTip(
            "Also look places up in OpenStreetMap's Nominatim service: what visitors type "
            "in the search box is sent to that service."
        )
        self.legendCheck = QCheckBox("Legend on the map and in exports")
        self.legendCheck.setObjectName("optionLegendCheck")
        self.downloadsCheck = QCheckBox("Data downloads (CSV, GeoJSON)")
        self.downloadsCheck.setObjectName("optionDownloadsCheck")
        self.downloadsCheck.setToolTip(
            "A Download button on every list. Anyone with the app's link can download the data."
        )

        self.overwriteEditsCheck = QCheckBox("A redeploy replaces the edits made in the web app")
        self.overwriteEditsCheck.setObjectName("optionOverwriteEditsCheck")
        self.overwriteEditsCheck.setToolTip(
            "Off (recommended): a redeploy keeps the features people added, moved or deleted in the app, "
            "even when the QGIS layer changed. On: the layer's rows are replaced by QGIS's, and those edits are lost."
        )

        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logoEdit, 1)
        logo_row.addWidget(self.logoButton)
        logo_row.addWidget(self.logoClearButton)
        color_row = QHBoxLayout()
        color_row.addWidget(self.colorEdit)
        color_row.addWidget(self.colorButton)
        color_row.addStretch(1)

        form = QFormLayout()
        form.addRow("Title", self.titleEdit)
        form.addRow("Logo", self._wrap(logo_row))
        form.addRow("Colour", self._wrap(color_row))
        form.addRow("Basemap", self.basemapCombo)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        for check in (
            self.searchCheck, self.geocoderCheck, self.legendCheck, self.downloadsCheck, self.overwriteEditsCheck
        ):
            layout.addWidget(check)

        self.logoButton.clicked.connect(self._choose_logo)
        self.logoClearButton.clicked.connect(lambda: self.logoEdit.setText(""))
        self.colorButton.clicked.connect(self._pick_color)
        self.searchCheck.toggled.connect(self._sync_geocoder)
        for signal in (
            self.titleEdit.textChanged,
            self.logoEdit.textChanged,
            self.colorEdit.textChanged,
            self.basemapCombo.currentIndexChanged,
            self.searchCheck.toggled,
            self.geocoderCheck.toggled,
            self.legendCheck.toggled,
            self.downloadsCheck.toggled,
            self.overwriteEditsCheck.toggled,
        ):
            signal.connect(self.changed)

        self.set_settings(None)

    @staticmethod
    def _wrap(layout):
        holder = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        holder.setLayout(layout)
        return holder

    # ------------------------------------------------------------------
    # Values
    # ------------------------------------------------------------------

    def settings(self):
        """What the run needs: ``core.web_options.project_info_extras``'s input."""
        return {
            "options": {
                "search": self.searchCheck.isChecked(),
                "geocoder": self.geocoderCheck.isChecked(),
                "legend": self.legendCheck.isChecked(),
                "downloads": self.downloadsCheck.isChecked(),
            },
            "title": self.titleEdit.text().strip(),
            "color": self.colorEdit.text().strip(),
            "basemap": self.basemapCombo.currentData(),
            "logo_path": self.logoEdit.text().strip(),
            "overwrite_edits": self.overwriteEditsCheck.isChecked(),
        }

    def set_settings(self, settings):
        """Shows ``settings`` (the shape of ``settings()``); ``None`` or missing keys
        give the defaults."""
        settings = settings or {}
        options = web_options.build_options(settings.get("options"))
        self.titleEdit.setText(settings.get("title") or "")
        self.logoEdit.setText(settings.get("logo_path") or "")
        self.colorEdit.setText(settings.get("color") or "")
        index = self.basemapCombo.findData(settings.get("basemap") or web_options.DEFAULT_BASEMAP)
        self.basemapCombo.setCurrentIndex(max(index, 0))
        self.searchCheck.setChecked(options["search"])
        self.geocoderCheck.setChecked(options["geocoder"])
        self.legendCheck.setChecked(options["legend"])
        self.downloadsCheck.setChecked(options["downloads"])
        self.overwriteEditsCheck.setChecked(bool(settings.get("overwrite_edits")))
        self._sync_geocoder()

    def set_default_title(self, text):
        """The project's title, shown greyed out while the title is left empty (the app
        then just uses the app name)."""
        self.titleEdit.setPlaceholderText(text or "")

    def problem(self):
        """Why the current choices cannot be used (a sentence for the user), or None."""
        problem = web_options.logo_problem(self.logoEdit.text().strip())
        if problem:
            return problem
        color = self.colorEdit.text().strip()
        if color and web_options.normalize_color(color) is None:
            return "The colour must be written as #rrggbb, for example #0b7a75."
        return None

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _sync_geocoder(self, *_):
        """Place search lives in the search box: without it, there is nothing to attach to."""
        enabled = self.searchCheck.isChecked()
        self.geocoderCheck.setEnabled(enabled)
        if not enabled:
            self.geocoderCheck.setChecked(False)

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a logo", "", "Images (*.png *.jpg *.jpeg *.svg *.webp)"
        )
        if path:
            self.logoEdit.setText(path)

    def _pick_color(self):
        start = QColor(web_options.normalize_color(self.colorEdit.text()) or "#1976d2")
        color = QColorDialog.getColor(start, self, "Choose the app's colour")
        if color.isValid():
            self.colorEdit.setText(color.name())
