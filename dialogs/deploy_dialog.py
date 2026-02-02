from PyQt5 import uic
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject, QgsMapLayer
import os
from ..core.gispublisher_runner import GISPublisherRunner

DEPLOY_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "deploy_dialog.ui")
)

DEPLOY_GENERATE_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "deploy_generate_dialog.ui")
)

DEPLOY_PROGRESS_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "deploy_progress.ui")
)


class DeployProgressDialog(QDialog, DEPLOY_PROGRESS_FORM_CLASS):
    """Dialog that shows the progress of the deployment."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.closeButton.setEnabled(False)


class DeployGenerateDialog(QDialog, DEPLOY_GENERATE_FORM_CLASS):
    """Dialog to select layers and folder before deployment."""
    def __init__(self, layers, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.layers = layers
        self.output_dir = None

        self.layersList.clear()
        for layer in self.layers:
            self.layersList.addItem(layer.name())

        self.deployButton.setEnabled(False)
        self.outputRequiredLabel.setVisible(True)

        self.selectFolderButton.clicked.connect(self.select_output_folder)
        self.deployButton.clicked.connect(self.start_deploy)
        self.cancelButton.clicked.connect(self.close)

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta de despliegue", "")
        if folder:
            self.output_dir = folder
            self.outputFolderLabel.setText(f"El producto se desplegará en: {folder}")
            self.deployButton.setEnabled(True)
            self.outputRequiredLabel.setVisible(False)
        else:
            self.outputRequiredLabel.setVisible(True)
            self.deployButton.setEnabled(False)

    def start_deploy(self):
        if not self.output_dir:
            QMessageBox.warning(self, "Atención", "Debes seleccionar una carpeta de salida.")
            return

        try:
            progress_dialog = DeployProgressDialog(parent=None)
            progress_dialog.setModal(True)
            progress_dialog.closeButton.clicked.connect(progress_dialog.close)
            progress_dialog.show()

            self.close() 

            self.runner = GISPublisherRunner(
                layers=self.layers,
                output_dir=self.output_dir,
                progress_label=progress_dialog.statusLabel,
                progress_bar=progress_dialog.progressBar,
                output_text=progress_dialog.outputText,
                parent=self,
                finished_callback=lambda: (
                    progress_dialog.closeButton.setEnabled(True)
                    self.deployButton.setEnabled(True),
                    self.cancelButton.setEnabled(True)
                )
            )
            self.runner.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


class DeployDialog(QDialog, DEPLOY_FORM_CLASS):
    """Main deployment dialog: choose Local/SSH/AWS."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.radioLocal.toggled.connect(self.update_stack)
        self.radioSSH.toggled.connect(self.update_stack)
        self.radioAWS.toggled.connect(self.update_stack)

        self.deployButton.clicked.connect(self.open_deploy_generate_dialog)

    def update_stack(self):
        if self.radioLocal.isChecked():
            self.deployWidget.setCurrentIndex(0)
        elif self.radioSSH.isChecked():
            self.deployWidget.setCurrentIndex(1)
        elif self.radioAWS.isChecked():
            self.deployWidget.setCurrentIndex(2)

    def open_deploy_generate_dialog(self):
        layers = [layer for layer in QgsProject.instance().mapLayers().values()
                  if layer.type() == QgsMapLayer.VectorLayer]

        if not layers:
            QMessageBox.warning(self, "Atención", "No hay capas vectoriales disponibles para desplegar.")
            return

        dlg = DeployGenerateDialog(layers, parent=self)
        dlg.exec_()
