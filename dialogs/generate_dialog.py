import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox
from ..core.gispublisher_runner import GISPublisherRunner

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "generate_dialog.ui")
)

PROGRESS_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "generate_progress.ui")
)


class GenerateProgressDialog(QDialog, PROGRESS_FORM_CLASS):
    """Dialog that shows progress while generating the product."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.closeButton.setEnabled(False)


class GenerateDialog(QDialog, FORM_CLASS):
    """Dialog to select layers and output folder for generation."""

    DEBUG = True
    
    def __init__(self, layers, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.layers = layers
        self.output_dir = None

        self.layersList.clear()
        for layer in self.layers:
            self.layersList.addItem(layer.name())

        self.generateButton.setEnabled(False)
        self.outputRequiredLabel.setVisible(True) 

        self.selectFolderButton.clicked.connect(self.select_output_folder)
        self.generateButton.clicked.connect(self.generate_product)
        self.cancelButton.clicked.connect(self.close)

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta de salida", "")
        if folder:
            self.output_dir = folder
            self.outputFolderLabel.setText(f"El producto se generará en: {folder}")
            self.generateButton.setEnabled(True)
            self.outputRequiredLabel.setVisible(False)
        else:
            self.outputRequiredLabel.setVisible(True)

    def generate_product(self):
        if not self.output_dir:
            return

        try:
            progress_dialog = GenerateProgressDialog(self)
            progress_dialog.closeButton.clicked.connect(progress_dialog.close)
            progress_dialog.outputText.setVisible(self.DEBUG)
            progress_dialog.show()  

            self.close()          

            self.runner = GISPublisherRunner(
                layers=self.layers,
                output_dir=self.output_dir,
                chart_folder=getattr(self.parent(), "selected_chart_folder", None),
                progress_label=progress_dialog.statusLabel,
                progress_bar=progress_dialog.progressBar,
                output_text=progress_dialog.outputText if self.DEBUG else None,
                parent=self,
                debug=self.DEBUG,
                finished_callback=lambda: (
                    progress_dialog.close() if not self.DEBUG else None,
                    self.close()
                )
            )
            self.runner.start(generate=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
