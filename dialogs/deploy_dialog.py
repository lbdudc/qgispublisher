from PyQt5 import uic
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import QgsProject, QgsMapLayer
import os, json, tempfile, pathlib, subprocess
from ..core.gispublisher_runner import GISPublisherRunner

DEPLOY_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "deploy_dialog.ui")
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

class DeployDialog(QDialog, DEPLOY_FORM_CLASS):
    """Main deployment dialog: choose Local/SSH/AWS."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.radioLocal.toggled.connect(self.update_stack)
        self.radioSSH.toggled.connect(self.update_stack)
        self.radioAWS.toggled.connect(self.update_stack)

        self.deployButton.clicked.connect(self.start_deploy)

        self.update_stack()

    def update_stack(self):
        if self.radioLocal.isChecked():
            self.deployWidget.setCurrentIndex(0)
        elif self.radioSSH.isChecked():
            self.deployWidget.setCurrentIndex(1)
        elif self.radioAWS.isChecked():
            self.deployWidget.setCurrentIndex(2)

    def get_gispublisher_root(self):
        result = subprocess.run(
            ["npm", "root", "-g"],
            capture_output=True,
            text=True,
            shell=True
        )
        npm_root = pathlib.Path(result.stdout.strip())
        return npm_root / "@lbdudc" / "gis-publisher"

    def generate_deploy_config(self):
        "Generates a temporary JSON according to the selected deployment type."

        gispublisher_root = self.get_gispublisher_root()

        platform_dir = gispublisher_root / "node_modules" / "@lbdudc" / "mini-lps" / "src" / "platform"

        base_json = {
            "name": "test",
            "version": "2.0.0",
            "platform": {
                "codePath": str(platform_dir / "code"),
                "featureModel": str(platform_dir / "model.xml"),
                "config": str(platform_dir / "config.json"),
                "extraJS": str(platform_dir / "extra.js"),
                "modelTransformation": str(platform_dir / "transformation.js")
            }
        }
        
        if self.radioLocal.isChecked():
            deploy_section = {
                "deploy": {"type": "local"},
                "host": self.localHostEdit.text() or "http://localhost:80"
            }

        elif self.radioSSH.isChecked():
            deploy_section = {
                "deploy": {
                    "type": "local",
                    "host": self.sshHostEdit.text(),
                    "port": int(self.sshPortEdit.text() or 22),
                    "username": self.sshUsernameEdit.text(),
                    "certRoute": self.sshCertRouteEdit.text(),
                    "remoteRepoPath": self.sshRemoteRepoPathEdit.text()
                },
                "host": self.sshHostEdit.text()
            }

        elif self.radioAWS.isChecked():
            deploy_section = {
                "deploy": {
                    "type": "aws",
                    "AWS_ACCESS_KEY_ID": self.awsAccessKeyEdit.text(),
                    "AWS_SECRET_ACCESS_KEY": self.awsSecretAccessKeyEdit.text(),
                    "AWS_REGION": self.awsRegionEdit.text(),
                    "AWS_AMI_ID": self.awsAmiIdEdit.text(),
                    "AWS_INSTANCE_TYPE": self.awsInstanceTypeEdit.text(),
                    "AWS_INSTANCE_NAME": self.awsInstanceNameEdit.text(),
                    "AWS_SECURITY_GROUP_ID": self.awsSecurityGroupEdit.text(),
                    "AWS_KEY_NAME": self.awsKeyNameEdit.text(),
                    "AWS_USERNAME": self.awsUsernameEdit.text(),
                    "AWS_SSH_PRIVATE_KEY_PATH": self.awsSshKeyPathEdit.text(),
                    "REMOTE_REPO_PATH": self.awsRemotePathEdit.text()
                }
            }

        else:
            raise ValueError("Tipo de despliegue no seleccionado.")

        final_json = {**base_json, **deploy_section}

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        with open(temp_file.name, "w") as f:
            json.dump(final_json, f, indent=4)

        return temp_file.name

    def start_deploy(self):
        layers = [layer for layer in QgsProject.instance().mapLayers().values()
                if layer.type() == QgsMapLayer.VectorLayer]

        if not layers:
            QMessageBox.warning(self, "Atención", "No hay capas vectoriales disponibles para desplegar.")
            return

        try:
            progress_dialog = DeployProgressDialog(parent=None)
            progress_dialog.setModal(True)
            progress_dialog.closeButton.clicked.connect(progress_dialog.close)
            progress_dialog.show()

            config_path = self.generate_deploy_config()

            if self.radioLocal.isChecked():
                os.environ["PATH"] += os.pathsep + r"C:\Program Files\Docker\Docker\resources\bin"

            self.runner = GISPublisherRunner(
                layers=layers,
                output_dir=None, 
                progress_label=progress_dialog.statusLabel,
                progress_bar=progress_dialog.progressBar,
                output_text=progress_dialog.outputText,
                parent=self,
                finished_callback=lambda: (
                    progress_dialog.closeButton.setEnabled(True),
                    os.remove(config_path)
                )
            )
            self.runner.start(config_path=config_path)

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

