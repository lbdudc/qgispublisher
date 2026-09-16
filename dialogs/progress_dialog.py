import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "progress_dialog.ui")
)


class ProgressDialog(QDialog, FORM_CLASS):
    """Generic dialog that shows the progress of a running GISPublisher process."""

    def __init__(self, title="Working...", parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle(title)
        self.closeButton.setText("Cancel")

    def set_finished_state(self):
        """Switch the button from 'Cancel' (running) to 'Close' (done)."""
        self.closeButton.setText("Close")
