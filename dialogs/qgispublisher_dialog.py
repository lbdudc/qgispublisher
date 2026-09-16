import os
import subprocess
import sys

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QFileDialog,
    QLineEdit,
    QListWidgetItem,
    QMessageBox,
    QStyle,
)
from qgis.core import QgsProject, QgsMapLayer

from .progress_dialog import ProgressDialog
from ..core.dependencies_checker import find_node, find_gispublisher, find_npm
from ..core.deploy_config import build_deploy_config
from ..core.gispublisher_runner import GISPublisherRunner

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "gispublisher_dialog.ui")
)

ACTION_PAGE_GENERATE = 0
ACTION_PAGE_DEPLOY = 1

DEPLOY_PAGE_LOCAL = 0
DEPLOY_PAGE_SSH = 1
DEPLOY_PAGE_AWS = 2


class InstallGisPublisherThread(QThread):
    """Runs `npm install -g @lbdudc/gis-publisher` off the UI thread."""

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


class GISPublisherDialog(QDialog, FORM_CLASS):
    """Main plugin dialog: layers, optional charts/models, and a Generate/Deploy action."""

    DEBUG = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.selected_chart_folder = None
        self.selected_model_folder = None
        self.output_dir = None
        self._node_result = None
        self._gispub_path = None

        self.selectAllButton.clicked.connect(self.on_select_all_layers)
        self.layersList.itemChanged.connect(self.update_selection_state)

        self.selectChartFolderButton.clicked.connect(self.select_chart_folder)
        self.clearChartFolderButton.clicked.connect(self.clear_chart_folder)
        self.selectAllChartsButton.clicked.connect(lambda: self.toggle_all_checked(self.chartFilesList))

        self.selectModelFolderButton.clicked.connect(self.select_model_folder)
        self.clearModelFolderButton.clicked.connect(self.clear_model_folder)
        self.selectAllModelsButton.clicked.connect(lambda: self.toggle_all_checked(self.modelFilesList))

        self.radioGenerate.toggled.connect(self.update_action_stack)
        self.radioDeploy.toggled.connect(self.update_action_stack)
        self.selectOutputFolderButton.clicked.connect(self.select_output_folder)

        self.radioLocal.toggled.connect(self.update_deploy_stack)
        self.radioSSH.toggled.connect(self.update_deploy_stack)
        self.radioAWS.toggled.connect(self.update_deploy_stack)

        self.installGispubButton.clicked.connect(self.install_gispublisher)
        self.refreshStatusButton.clicked.connect(self.check_requirements)

        self.runButton.clicked.connect(self.on_run_clicked)
        self.cancelButton.clicked.connect(self.close)

        self.setup_deploy_help()
        self.setup_icons()
        self.update_action_stack()
        self.update_deploy_stack()

        self.contentSplitter.setSizes([260, 400])

        QgsProject.instance().layersAdded.connect(self.load_layers)
        QgsProject.instance().layersRemoved.connect(self.load_layers)
        self.load_layers()
        self.check_requirements()

    # ------------------------------------------------------------------
    # Generic checkable-list helpers (layers / chart files / model files)
    # ------------------------------------------------------------------

    def toggle_all_checked(self, list_widget):
        count = list_widget.count()
        if count == 0:
            return

        all_checked = all(
            list_widget.item(i).checkState() == Qt.Checked for i in range(count)
        )
        new_state = Qt.Unchecked if all_checked else Qt.Checked

        for i in range(count):
            list_widget.item(i).setCheckState(new_state)

    def get_checked_texts(self, list_widget):
        return [
            list_widget.item(i).text()
            for i in range(list_widget.count())
            if list_widget.item(i).checkState() == Qt.Checked
        ]

    def populate_file_list(self, list_widget, folder):
        list_widget.clear()
        try:
            entries = sorted(os.listdir(folder))
        except OSError:
            entries = []

        for name in entries:
            item = QListWidgetItem(name)
            item.setCheckState(Qt.Checked)
            list_widget.addItem(item)

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def load_layers(self):
        self.layersList.clear()

        project = QgsProject.instance()
        layers = project.mapLayers().values()

        for layer in layers:
            if layer.type() not in (QgsMapLayer.VectorLayer, QgsMapLayer.RasterLayer):
                continue

            item = QListWidgetItem(layer.name())
            item.setData(Qt.UserRole, layer.id())
            item.setCheckState(Qt.Checked)

            self.layersList.addItem(item)

        self.update_selection_state()

    def on_select_all_layers(self):
        self.toggle_all_checked(self.layersList)
        self.update_selection_state()

    def update_selection_state(self):
        has_selected = any(
            self.layersList.item(i).checkState() == Qt.Checked
            for i in range(self.layersList.count())
        )
        self.infoLabel.setVisible(not has_selected)

    def get_selected_layers(self):
        project = QgsProject.instance()
        selected_layers = []

        for i in range(self.layersList.count()):
            item = self.layersList.item(i)
            if item.checkState() == Qt.Checked:
                layer = project.mapLayer(item.data(Qt.UserRole))
                if layer:
                    selected_layers.append(layer)

        return selected_layers

    # ------------------------------------------------------------------
    # Charts / models folders
    # ------------------------------------------------------------------

    def select_chart_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select charts folder", "")
        if folder:
            self.selected_chart_folder = folder
            self.chartFolderPathLabel.setText(folder)
            self.populate_file_list(self.chartFilesList, folder)

    def clear_chart_folder(self):
        self.selected_chart_folder = None
        self.chartFolderPathLabel.setText("No folder selected")
        self.chartFilesList.clear()

    def get_selected_chart_items(self):
        if not self.selected_chart_folder:
            return None
        return self.get_checked_texts(self.chartFilesList)

    def select_model_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select models folder", "")
        if folder:
            self.selected_model_folder = folder
            self.modelFolderPathLabel.setText(folder)
            self.populate_file_list(self.modelFilesList, folder)

    def clear_model_folder(self):
        self.selected_model_folder = None
        self.modelFolderPathLabel.setText("No folder selected")
        self.modelFilesList.clear()

    def get_selected_model_items(self):
        if not self.selected_model_folder:
            return None
        return self.get_checked_texts(self.modelFilesList)

    # ------------------------------------------------------------------
    # Action (Generate / Deploy) switching
    # ------------------------------------------------------------------

    def update_action_stack(self):
        if self.radioGenerate.isChecked():
            self.actionStack.setCurrentIndex(ACTION_PAGE_GENERATE)
        else:
            self.actionStack.setCurrentIndex(ACTION_PAGE_DEPLOY)

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select output folder", "")
        if folder:
            self.output_dir = folder
            self.outputFolderLabel.setStyleSheet("")
            self.outputFolderLabel.setText(folder)

    # ------------------------------------------------------------------
    # Deploy page: help text, browse actions, stack switching, validation
    # ------------------------------------------------------------------

    def setup_deploy_help(self):
        self.add_browse_action(self.sshCertRouteEdit, "Select private key file")
        self.add_browse_action(self.awsSshKeyPathEdit, "Select SSH key file")

        self.localHintLabel.setOpenExternalLinks(True)
        self.localHintLabel.setText(
            "Runs the generated application locally using Docker.<br>"
            "Make sure <a href='https://www.docker.com/products/docker-desktop/'>Docker Desktop</a> "
            "is installed and running before deploying."
        )

        self.sshHintLabel.setText(
            "Deploys to a server you control over SSH.<br>"
            "You'll need an existing SSH-enabled account and a private key already "
            "authorized on that server."
        )

        self.awsCredentialsHintLabel.setOpenExternalLinks(True)
        self.awsCredentialsHintLabel.setText(
            "Create or find these under AWS Console \u2192 IAM \u2192 Users \u2192 Security credentials.<br>"
            "See the <a href='https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html'>"
            "AWS IAM access keys documentation</a>."
        )
        self.awsInstanceHintLabel.setOpenExternalLinks(True)
        self.awsInstanceHintLabel.setText(
            "AMI, instance type, security group and key pair are managed in the EC2 Console.<br>"
            "See the <a href='https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instances.html'>"
            "AWS EC2 documentation</a>."
        )
        self.awsSshHintLabel.setText(
            "The SSH key path must point to the private key matching the key pair above, "
            "used to connect to the instance once it launches."
        )

        tooltips = {
            self.localHostEdit: "URL the application will be served on once deployed, e.g. http://localhost:80.",
            self.sshHostEdit: "Address of the remote server to deploy to.",
            self.sshUsernameEdit: "SSH username used to connect to the remote server.",
            self.sshPortEdit: "SSH port on the remote server (default 22).",
            self.sshCertRouteEdit: "Path to the private key (.pem) used to authenticate over SSH.",
            self.sshRemoteRepoPathEdit: "Absolute path on the remote server where the application will be deployed.",
            self.awsAccessKeyEdit: "AWS IAM access key ID with permission to launch EC2 instances.",
            self.awsSecretAccessKeyEdit: "AWS IAM secret access key matching the access key above.",
            self.awsRegionEdit: "AWS region code, e.g. eu-west-1.",
            self.awsAmiIdEdit: "ID of the Amazon Machine Image to launch, e.g. ami-0123456789abcdef0 (EC2 \u2192 AMI Catalog).",
            self.awsInstanceTypeEdit: "EC2 instance size, e.g. t2.micro (EC2 \u2192 Instance Types).",
            self.awsInstanceNameEdit: "Name tag to give the created EC2 instance.",
            self.awsSecurityGroupEdit: "ID of an existing security group, e.g. sg-0123456789abcdef0 (EC2 \u2192 Security Groups).",
            self.awsKeyNameEdit: "Name of an existing EC2 key pair, not a file path (EC2 \u2192 Key Pairs).",
            self.awsUsernameEdit: "SSH username used to connect to the EC2 instance once it launches.",
            self.awsSshKeyPathEdit: "Local path to the private key matching the selected AWS key pair.",
            self.awsRemotePathEdit: "Absolute path on the EC2 instance where the application will be deployed.",
        }
        for widget, text in tooltips.items():
            widget.setToolTip(text)

    def setup_icons(self):
        """Use native Qt standard icons instead of emoji for a consistent, platform-correct look."""
        style = self.style()

        self.dataTabs.setTabIcon(0, style.standardIcon(QStyle.SP_DirIcon))
        self.dataTabs.setTabIcon(1, style.standardIcon(QStyle.SP_FileDialogContentsView))
        self.dataTabs.setTabIcon(2, style.standardIcon(QStyle.SP_FileDialogInfoView))

        self.selectChartFolderButton.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.selectModelFolderButton.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.selectOutputFolderButton.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))

        self.clearChartFolderButton.setIcon(style.standardIcon(QStyle.SP_DialogResetButton))
        self.clearModelFolderButton.setIcon(style.standardIcon(QStyle.SP_DialogResetButton))

        self.installGispubButton.setIcon(style.standardIcon(QStyle.SP_ArrowDown))
        self.refreshStatusButton.setIcon(style.standardIcon(QStyle.SP_BrowserReload))

        self.runButton.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.cancelButton.setIcon(style.standardIcon(QStyle.SP_DialogCancelButton))

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

    def update_deploy_stack(self):
        if self.radioLocal.isChecked():
            self.deployWidget.setCurrentIndex(DEPLOY_PAGE_LOCAL)
        elif self.radioSSH.isChecked():
            self.deployWidget.setCurrentIndex(DEPLOY_PAGE_SSH)
        elif self.radioAWS.isChecked():
            self.deployWidget.setCurrentIndex(DEPLOY_PAGE_AWS)

    def current_deploy_type(self):
        if self.radioLocal.isChecked():
            return "local"
        if self.radioSSH.isChecked():
            return "ssh"
        return "aws"

    def validate_deploy_fields(self):
        """Return a list of missing required field labels for the selected deployment type."""
        deploy_type = self.current_deploy_type()
        missing = []

        if deploy_type == "ssh":
            required = [
                (self.sshHostEdit, "Host"),
                (self.sshUsernameEdit, "Username"),
                (self.sshCertRouteEdit, "Private key path"),
                (self.sshRemoteRepoPathEdit, "Remote repository path"),
            ]
            missing.extend(label for widget, label in required if not widget.text().strip())

        elif deploy_type == "aws":
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

    def collect_deploy_fields(self):
        deploy_type = self.current_deploy_type()

        if deploy_type == "local":
            fields = {"host": self.localHostEdit.text()}
        elif deploy_type == "ssh":
            fields = {
                "host": self.sshHostEdit.text(),
                "port": self.sshPortEdit.value(),
                "username": self.sshUsernameEdit.text(),
                "cert_route": self.sshCertRouteEdit.text(),
                "remote_repo_path": self.sshRemoteRepoPathEdit.text(),
            }
        else:
            fields = {
                "access_key": self.awsAccessKeyEdit.text(),
                "secret_key": self.awsSecretAccessKeyEdit.text(),
                "region": self.awsRegionEdit.text(),
                "ami_id": self.awsAmiIdEdit.text(),
                "instance_type": self.awsInstanceTypeEdit.text(),
                "instance_name": self.awsInstanceNameEdit.text(),
                "security_group": self.awsSecurityGroupEdit.text(),
                "key_name": self.awsKeyNameEdit.text(),
                "username": self.awsUsernameEdit.text(),
                "ssh_key_path": self.awsSshKeyPathEdit.text(),
                "remote_path": self.awsRemotePathEdit.text(),
            }

        return deploy_type, fields

    # ------------------------------------------------------------------
    # Requirements / status
    # ------------------------------------------------------------------

    def check_requirements(self):
        self._node_result = find_node()
        node_ok = self._node_result["installed"]

        try:
            self._gispub_path = find_gispublisher()
            gispub_ok = True
            gispub_message = f"GISPublisher found at: {self._gispub_path}"
        except Exception as e:
            self._gispub_path = None
            gispub_ok = False
            gispub_message = str(e)

        detail_parts = [
            f"Node.js found at: {self._node_result['path']}"
            if node_ok
            else f"Node.js: {self._node_result['message']}",
            gispub_message if gispub_ok else f"GISPublisher: {gispub_message}",
        ]
        self.statusSummaryLabel.setToolTip("\n".join(detail_parts))

        if node_ok and gispub_ok:
            self.statusSummaryLabel.setStyleSheet("color: #666666;")
            self.statusSummaryLabel.setText("✔ Requirements OK")
        else:
            self.statusSummaryLabel.setStyleSheet("color: #cc8400;")
            self.statusSummaryLabel.setText("⚠ Requirements missing — hover for details")

        self.installGispubButton.setVisible(node_ok and not gispub_ok)

    def requirements_met(self):
        return bool(self._node_result and self._node_result["installed"] and self._gispub_path)

    def install_gispublisher(self):
        QMessageBox.information(
            self,
            "GISPublisher Installation",
            "The following command will be executed:\n\nnpm install -g @lbdudc/gis-publisher",
        )

        self.installGispubButton.setEnabled(False)
        self.statusSummaryLabel.setText("Installing GISPublisher... this may take a few minutes.")

        self.install_thread = InstallGisPublisherThread()
        self.install_thread.finished_ok.connect(self._install_ok)
        self.install_thread.finished_error.connect(self._install_error)
        self.install_thread.start()

    def _install_ok(self):
        self.installGispubButton.setEnabled(True)
        QMessageBox.information(self, "Installation completed", "GISPublisher was installed successfully.")
        self.check_requirements()

    def _install_error(self, error):
        self.installGispubButton.setEnabled(True)
        QMessageBox.critical(self, "Error installing GISPublisher", error)
        self.check_requirements()

    # ------------------------------------------------------------------
    # Run (Generate / Deploy)
    # ------------------------------------------------------------------

    def on_run_clicked(self):
        selected_layers = self.get_selected_layers()
        if not selected_layers:
            QMessageBox.warning(self, "No layers selected", "Select at least one layer to continue.")
            return

        self.check_requirements()
        if not self.requirements_met():
            QMessageBox.warning(
                self,
                "Requirements not met",
                "Node.js and/or GISPublisher are missing. See the message at the top of the window "
                "and use the Install button if needed.",
            )
            return

        if self.radioGenerate.isChecked():
            self.run_generate(selected_layers)
        else:
            self.run_deploy(selected_layers)

    def run_generate(self, selected_layers):
        if not self.output_dir:
            QMessageBox.warning(self, "Output folder required", "Select an output folder before generating.")
            return

        progress_dialog = ProgressDialog(title="Generating...", parent=self)
        progress_dialog.outputText.setVisible(self.DEBUG)
        progress_dialog.show()

        self.runner = GISPublisherRunner(
            layers=selected_layers,
            output_dir=self.output_dir,
            chart_folder=self.selected_chart_folder,
            chart_items=self.get_selected_chart_items(),
            model_folder=self.selected_model_folder,
            model_items=self.get_selected_model_items(),
            progress_label=progress_dialog.statusLabel,
            progress_bar=progress_dialog.progressBar,
            output_text=progress_dialog.outputText if self.DEBUG else None,
            parent=self,
            debug=self.DEBUG,
            finished_callback=lambda: self.on_generate_finished(progress_dialog),
        )
        progress_dialog.closeButton.clicked.connect(self.runner.cancel)

        try:
            self.runner.start(generate=True)
        except Exception as e:
            progress_dialog.close()
            QMessageBox.critical(self, "Error", str(e))

    def on_generate_finished(self, progress_dialog):
        progress_dialog.set_finished_state()
        progress_dialog.closeButton.clicked.disconnect()
        progress_dialog.closeButton.clicked.connect(progress_dialog.close)
        if not self.DEBUG:
            progress_dialog.close()

    def run_deploy(self, selected_layers):
        missing = self.validate_deploy_fields()
        if missing:
            QMessageBox.warning(
                self,
                "Missing information",
                "Please fill in the following required field(s):\n\n- " + "\n- ".join(missing),
            )
            return

        deploy_type, fields = self.collect_deploy_fields()

        try:
            config_path = build_deploy_config(deploy_type, fields)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        if deploy_type == "local" and sys.platform == "win32":
            docker_bin = r"C:\Program Files\Docker\Docker\resources\bin"
            if os.path.isdir(docker_bin):
                os.environ["PATH"] += os.pathsep + docker_bin

        progress_dialog = ProgressDialog(title="Deploying...", parent=self)
        progress_dialog.outputText.setVisible(self.DEBUG)
        progress_dialog.show()

        self.runner = GISPublisherRunner(
            layers=selected_layers,
            output_dir=None,
            chart_folder=self.selected_chart_folder,
            chart_items=self.get_selected_chart_items(),
            model_folder=self.selected_model_folder,
            model_items=self.get_selected_model_items(),
            progress_label=progress_dialog.statusLabel,
            progress_bar=progress_dialog.progressBar,
            output_text=progress_dialog.outputText if self.DEBUG else None,
            parent=self,
            debug=self.DEBUG,
            finished_callback=lambda: self.on_deploy_finished(progress_dialog, config_path),
        )
        progress_dialog.closeButton.clicked.connect(self.runner.cancel)

        try:
            self.runner.start(config_path=config_path)
        except Exception as e:
            progress_dialog.close()
            os.remove(config_path)
            QMessageBox.critical(self, "Error", str(e))

    def on_deploy_finished(self, progress_dialog, config_path):
        progress_dialog.set_finished_state()
        progress_dialog.closeButton.clicked.disconnect()
        progress_dialog.closeButton.clicked.connect(progress_dialog.close)
        if not self.DEBUG:
            progress_dialog.close()
        os.remove(config_path)
