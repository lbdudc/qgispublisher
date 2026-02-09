import os
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QListWidgetItem
from qgis.core import QgsProject, QgsMapLayer
from .generate_dialog import GenerateDialog
from .deploy_dialog import DeployDialog
from .requirements_dialog import RequirementsDialog
from ..core.dependencies_checker import check_node_gispublisher

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
        self.selectAllButton.clicked.connect(self.select_all_layers)

        QgsProject.instance().layersAdded.connect(self.load_layers)
        QgsProject.instance().layersRemoved.connect(self.load_layers)
        self.load_layers()

    def load_layers(self):
        self.layersList.clear()

        project = QgsProject.instance()
        layers = project.mapLayers().values()

        for layer in layers:
            if layer.type() != QgsMapLayer.VectorLayer:
                continue

            item = QListWidgetItem(layer.name())
            item.setData(Qt.UserRole, layer.id())
            item.setCheckState(Qt.Checked)

            self.layersList.addItem(item)

        has_layers = self.layersList.count() > 0
        self.generateButton.setEnabled(has_layers)
        self.deployButton.setEnabled(has_layers)
        self.infoLabel.setVisible(not has_layers)

    def check_requirements_and_open(self, create_dialog_callback):
        """Check requirements and open the dialog using the provided callback if all are satisfied."""
        req_dialog = RequirementsDialog(parent=self)

        if req_dialog.nodeIconLabel.text() == "✔" and req_dialog.gispubIconLabel.text() == "✔":
            dlg = create_dialog_callback()
            dlg.exec_()
        else:
            req_dialog.exec_()

    def select_all_layers(self):
        count = self.layersList.count()
        if count == 0:
            return

        all_checked = True
        for i in range(count):
            if self.layersList.item(i).checkState() != Qt.Checked:
                all_checked = False
                break

        new_state = Qt.Unchecked if all_checked else Qt.Checked

        for i in range(count):
            self.layersList.item(i).setCheckState(new_state)

    def open_generate_dialog(self):
        project = QgsProject.instance()
        selected_layers = []

        for i in range(self.layersList.count()):
            item = self.layersList.item(i)
            if item.checkState() == Qt.Checked:
                layer_id = item.data(Qt.UserRole)
                layer = project.mapLayer(layer_id)
                if layer:
                    selected_layers.append(layer)

        if not selected_layers:
            return

        self.check_requirements_and_open(lambda: GenerateDialog(selected_layers, parent=self))

    def open_deploy_dialog(self):
        self.check_requirements_and_open(lambda: DeployDialog(parent=self))