import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.core import QgsSettings

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "progress_dialog.ui")
)

_SHOW_LOG_SETTING = "GISPublisher/showLog"


class ProgressDialog(QDialog, FORM_CLASS):
    """Generic dialog that shows the progress of a running GISPublisher process."""

    def __init__(self, title="Working...", parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle(title)
        self.closeButton.setText("Cancel")

        settings = QgsSettings()
        show_log = settings.value(_SHOW_LOG_SETTING, False, type=bool)
        self.showLogCheckBox.setChecked(show_log)
        self.outputText.setVisible(show_log)
        self.showLogCheckBox.toggled.connect(self._on_show_log_toggled)

    def _on_show_log_toggled(self, checked):
        self.outputText.setVisible(checked)
        QgsSettings().setValue(_SHOW_LOG_SETTING, checked)

    def set_finished_state(self):
        """Switch the button from 'Cancel' (running) to 'Close' (done)."""
        self.closeButton.setText("Close")
