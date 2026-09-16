import sys
from PyQt5 import uic
from PyQt5.QtWidgets import QAction, QDialog, QFileDialog, QLineEdit, QMessageBox, QStyle
import os, json, tempfile, pathlib, subprocess
from ..core.gispublisher_runner import GISPublisherRunner
from ..core.dependencies_checker import find_npm

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
        self.closeButton.setText("Cancel")

    def set_finished_state(self):
        """Switch the button from 'Cancel' (running) to 'Close' (done)."""
        self.closeButton.setText("Close")

class DeployDialog(QDialog, DEPLOY_FORM_CLASS):
    """Main deployment dialog: choose Local/SSH/AWS.""" 

    DEBUG = False

    def __init__(self, layers, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.layers = layers

        self.radioLocal.toggled.connect(self.update_stack)
        self.radioSSH.toggled.connect(self.update_stack)
        self.radioAWS.toggled.connect(self.update_stack)

        self.deployButton.clicked.connect(self.start_deploy)
        self.cancelButton.clicked.connect(self.close)

        self.setup_field_helpers()
        self.update_stack()

    def setup_field_helpers(self):
        """Mask secrets, add browse actions for file paths, and add tooltips."""
        self.awsSecretAccessKeyEdit.setEchoMode(QLineEdit.Password)

        self.add_browse_action(self.sshCertRouteEdit, "Select private key file")
        self.add_browse_action(self.awsSshKeyPathEdit, "Select SSH key file")

        tooltips = {
            self.sshCertRouteEdit: "Path to the private key (.pem) used to authenticate over SSH.",
            self.sshRemoteRepoPathEdit: "Absolute path on the remote server where the application will be deployed.",
            self.awsAmiIdEdit: "ID of the Amazon Machine Image used to launch the instance (e.g. ami-0123456789abcdef0).",
            self.awsInstanceTypeEdit: "AWS EC2 instance type (e.g. t2.micro).",
            self.awsSecurityGroupEdit: "ID of the AWS security group to attach to the instance (e.g. sg-0123456789abcdef0).",
            self.awsKeyNameEdit: "Name of the EC2 key pair registered in AWS, used to launch the instance.",
            self.awsSshKeyPathEdit: "Local path to the private key matching the selected AWS key pair.",
            self.awsRemotePathEdit: "Absolute path on the remote instance where the application will be deployed.",
        }
        for widget, text in tooltips.items():
            widget.setToolTip(text)

    def add_browse_action(self, line_edit, dialog_title):
        """Add a clickable folder icon inside a QLineEdit to browse for a file."""
        icon = self.style().standardIcon(QStyle.SP_DialogOpenButton)
        action = QAction(icon, dialog_title, line_edit)
        action.triggered.connect(lambda: self.browse_for_file(line_edit, dialog_title))
        line_edit.addAction(action, QLineEdit.TrailingPosition)

    def browse_for_file(self, line_edit, dialog_title):
        path, _ = QFileDialog.getOpenFileName(self, dialog_title, line_edit.text())
        if path:
            line_edit.setText(path)

    def validate_fields(self):
        """Return a list of missing required field labels for the selected deployment type."""
        missing = []

        if self.radioLocal.isChecked():
            if not self.localHostEdit.text().strip():
                missing.append("Host")

        elif self.radioSSH.isChecked():
            required = [
                (self.sshHostEdit, "Host"),
                (self.sshUsernameEdit, "Username"),
                (self.sshCertRouteEdit, "Private key path"),
                (self.sshRemoteRepoPathEdit, "Remote repository path"),
            ]
            missing.extend(label for widget, label in required if not widget.text().strip())

        elif self.radioAWS.isChecked():
            required = [
                (self.awsAccessKeyEdit, "Access key"),
                (self.awsSecretAccessKeyEdit, "Secret key"),
                (self.awsRegionEdit, "Region"),
                (self.awsAmiIdEdit, "AMI ID"),
                (self.awsInstanceTypeEdit, "Instance type"),
                (self.awsInstanceNameEdit, "Instance name"),
                (self.awsSecurityGroupEdit, "Security group ID"),
                (self.awsKeyNameEdit, "Key pair"),
                (self.awsUsernameEdit, "SSH username"),
                (self.awsSshKeyPathEdit, "SSH key path"),
                (self.awsRemotePathEdit, "Remote repository path"),
            ]
            missing.extend(label for widget, label in required if not widget.text().strip())

        return missing

    def update_stack(self):
        if self.radioLocal.isChecked():
            self.deployWidget.setCurrentIndex(0)
        elif self.radioSSH.isChecked():
            self.deployWidget.setCurrentIndex(1)
        elif self.radioAWS.isChecked():
            self.deployWidget.setCurrentIndex(2)

    def get_gispublisher_root(self):
        result = subprocess.run(  # nosec B603 - find_npm() returns a fully-resolved path
            [find_npm(), "root", "-g"],
            capture_output=True,
            text=True,
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
                    "type": "ssh",
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
            raise ValueError("No deployment type selected.")

        final_json = {**base_json, **deploy_section}

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        with open(temp_file.name, "w") as f:
            json.dump(final_json, f, indent=4)

        return temp_file.name

    def start_deploy(self):
        if not self.layers:
            QMessageBox.warning(self, "Warning", "No layers selected to deploy.")
            return

        missing = self.validate_fields()
        if missing:
            QMessageBox.warning(
                self,
                "Missing information",
                "Please fill in the following required field(s):\n\n- " + "\n- ".join(missing),
            )
            return

        try:
            progress_dialog = DeployProgressDialog(parent=None)
            progress_dialog.setModal(True)
            progress_dialog.outputText.setVisible(self.DEBUG)
            progress_dialog.show()

            config_path = self.generate_deploy_config()

            if self.radioLocal.isChecked() and sys.platform == "win32":
                docker_bin = r"C:\Program Files\Docker\Docker\resources\bin"
                if os.path.isdir(docker_bin):
                    os.environ["PATH"] += os.pathsep + docker_bin

            self.runner = GISPublisherRunner(
                layers=self.layers,
                output_dir=None, 
                chart_folder=getattr(self.parent(), "selected_chart_folder", None),
                progress_label=progress_dialog.statusLabel,
                progress_bar=progress_dialog.progressBar,
                output_text=progress_dialog.outputText if self.DEBUG else None,
                parent=self,
                debug=self.DEBUG,
                finished_callback=lambda: self.on_deploy_finished(progress_dialog, config_path)
            )
            progress_dialog.closeButton.clicked.connect(self.runner.cancel)
            self.runner.start(config_path=config_path)

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_deploy_finished(self, progress_dialog, config_path):
        progress_dialog.set_finished_state()
        progress_dialog.closeButton.clicked.disconnect()
        progress_dialog.closeButton.clicked.connect(progress_dialog.close)
        if not self.DEBUG:
            progress_dialog.close()
        self.close()
        os.remove(config_path)

