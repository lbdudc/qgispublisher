from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

import os
from .dialogs.qgispublisher_dialog import GISPublisherDialog
from .core.publish_job import PublishJobManager

class GISPublisherPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None
        # Lives as long as the plugin, not the dialog: a running Generate/Deploy
        # keeps going (and is shown in the QGIS task manager) when the dialog or
        # the progress window is closed.
        self.job_manager = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icons", "qgispublisher.svg")
        self.action = QAction(QIcon(icon_path), "GISPublisher", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&GISPublisher", self.action)
        self.job_manager = PublishJobManager(self.iface, self.iface.mainWindow())

    def unload(self):
        # Stop a running job first: its process must not outlive the plugin
        if self.job_manager is not None:
            self.job_manager.shutdown()
            self.job_manager.deleteLater()
            self.job_manager = None
        # Close dialog if open
        if self.dialog is not None:
            self.dialog.close()
            self.dialog = None
        # Remove toolbar icon
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&GISPublisher", self.action)
            self.action = None

    def run(self):
        if self.dialog is None:
            self.dialog = GISPublisherDialog(self.iface.mainWindow(), job_manager=self.job_manager)
        self.dialog.show()
        self.dialog.raise_()

