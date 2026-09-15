import os
import sys
from PyQt5 import uic
import subprocess
from PyQt5.QtWidgets import QProgressDialog, QDialog, QMessageBox
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from ..core.dependencies_checker import find_node, find_npm, find_gispublisher

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "requirements_dialog.ui")
)

class InstallGisPublisherThread(QThread):
    finished_ok = pyqtSignal()
    finished_error = pyqtSignal(str)

    def run(self):
        try:
            npm_path = find_npm()
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.run(  # nosec B603 - npm_path is a fully-resolved path from shutil.which()
                [npm_path, "install", "-g", "@lbdudc/gis-publisher"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                **kwargs,
            )
            self.finished_ok.emit()
        except Exception as e:
            self.finished_error.emit(str(e))


class RequirementsDialog(QDialog, FORM_CLASS):
    """Dialog that shows Node.js and GISPublisher requirements."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.nodeInfoLabel.setTextFormat(Qt.RichText)
        self.nodeInfoLabel.setOpenExternalLinks(True)
        
        self.nodeIconLabel.setText("❌")
        self.gispubIconLabel.setText("❌")
        self.nodeInfoLabel.setText("")
        self.gispubInfoLabel.setText("")

        self.check_requirements()

        self.installGispubButton.clicked.connect(self.install_gispublisher)
        self.closeButton.clicked.connect(self.close)

    def check_requirements(self):
        # Node.js
        node_result = find_node()

        if node_result["installed"]:
            self.nodeIconLabel.setText("✔")
            self.nodeInfoLabel.setText(
                f"Node.js found at:<br>{node_result['path']}"
            )
        else:
            self.nodeIconLabel.setText("❌")
            self.nodeInfoLabel.setText(node_result["message"])

        # GISPublisher
        try:
            gispub_path = find_gispublisher()
            self.gispubIconLabel.setText("✔")
            self.gispubInfoLabel.setText(f"GISPublisher found at: {gispub_path}")
            self.installGispubButton.setEnabled(False)
        except Exception as e:
            self.gispubIconLabel.setText("❌")
            self.gispubInfoLabel.setText(str(e))
            self.installGispubButton.setEnabled(True)

    def install_gispublisher(self):
        QMessageBox.information(
            self,
            "GISPublisher Installation",
            "The following command will be executed:\n\nnpm install -g @lbdudc/gis-publisher"
        )

        self.progress = QProgressDialog(
            "Installing GISPublisher...\nThis may take a few minutes.",
            None,
            0,
            0,
            self
        )
        self.progress.setWindowTitle("Installing")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setCancelButton(None)
        self.progress.show()

        self.install_thread = InstallGisPublisherThread()
        self.install_thread.finished_ok.connect(self._install_ok)
        self.install_thread.finished_error.connect(self._install_error)
        self.install_thread.start()

    def _install_ok(self):
        self.progress.close()
        QMessageBox.information(
            self,
            "Installation completed",
            "GISPublisher was installed successfully."
        )
        self.check_requirements()

    def _install_error(self, error):
        self.progress.close()
        QMessageBox.critical(
            self,
            "Error installing GISPublisher",
            error
        )
