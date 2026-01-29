import os
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog
from qgis.core import QgsProject, QgsMapLayer
from .generate_dialog import GenerateDialog
from .deploy_dialog import DeployDialog

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "gispublisher_dialog.ui")
)

class GISPublisherDialog(QDialog, FORM_CLASS):
    """Main plugin dialog: list layers, launch generate/deploy dialogs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.infoLabel.setVisible(False)

        self.generateButton.clicked.connect(self.open_generate_dialog)
        self.deployButton.clicked.connect(self.open_deploy_dialog)
        self.cancelButton.clicked.connect(self.close)

        QgsProject.instance().layersAdded.connect(self.load_layers)
        QgsProject.instance().layersRemoved.connect(self.load_layers)
        self.load_layers()

    def load_layers(self):
        self.layersList.clear()
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.type() == QgsMapLayer.VectorLayer:
                self.layersList.addItem(layer.name())
        has_layers = self.layersList.count() > 0
        self.generateButton.setEnabled(has_layers)
        self.deployButton.setEnabled(has_layers)
        self.infoLabel.setVisible(not has_layers)

    def open_generate_dialog(self):
        layers = [layer for layer in QgsProject.instance().mapLayers().values()
                  if layer.type() == QgsMapLayer.VectorLayer]
        if not layers:
            return
        dlg = GenerateDialog(layers, parent=self)
        dlg.exec_()

    def open_deploy_dialog(self):
        dlg = DeployDialog(parent=self)
        dlg.exec_()
