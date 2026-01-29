from PyQt5 import QtWidgets, uic
import os

class DeployDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        ui_path = os.path.join(os.path.dirname(__file__), "ui", "deploy_dialog.ui")
        uic.loadUi(ui_path, self)

        self.radioLocal.toggled.connect(self.update_stack)
        self.radioSSH.toggled.connect(self.update_stack)
        self.radioAWS.toggled.connect(self.update_stack)

    def update_stack(self):
        if self.radioLocal.isChecked():
            self.deployWidget.setCurrentIndex(0)
        elif self.radioSSH.isChecked():
            self.deployWidget.setCurrentIndex(1)
        elif self.radioAWS.isChecked():
            self.deployWidget.setCurrentIndex(2)
