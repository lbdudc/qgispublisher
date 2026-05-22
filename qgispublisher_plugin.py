from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

import os
from .dialogs.qgispublisher_dialog import GISPublisherDialog

class GISPublisherPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icons", "qgispublisher.svg")
        self.action = QAction(QIcon(icon_path), "GISPublisher", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&GISPublisher", self.action)

    def unload(self):
        # Close dialog if open
        if hasattr(self, 'dialog') and self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        # Remove toolbar icon
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&GISPublisher", self.action)
            self.action = None

    def run(self):
        if not hasattr(self, 'dialog') or self.dialog is None:
            self.dialog = GISPublisherDialog(self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()

