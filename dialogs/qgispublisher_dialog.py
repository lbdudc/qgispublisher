import os
import subprocess
import sys

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QThread, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
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
from .chart_builder_dialog import ChartBuilderDialog
from ..core.dependencies_checker import find_node, find_gispublisher, find_npm
from ..core.deploy_config import build_deploy_config
from ..core.gispublisher_runner import GISPublisherRunner, cleanup_old_temp_dirs
from ..core import model_discovery, state_store, chart_builder, naming

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "gispublisher_dialog.ui")
)

ACTION_PAGE_GENERATE = 0
ACTION_PAGE_DEPLOY = 1

DEPLOY_PAGE_LOCAL = 0
DEPLOY_PAGE_SSH = 1
DEPLOY_PAGE_AWS = 2

# Deploy-form field -> widget, per deploy type, used to restore non-secret fields
# from deploy history. Credential/host-identity fields (AWS keys, SSH username/key
# paths) are never stored in history, so they're never restored either.
_RESTORE_FIELD_WIDGETS = {
    "local": lambda self: {"host": self.localHostEdit},
    "ssh": lambda self: {
        "host": self.sshHostEdit,
        "port": self.sshPortEdit,
        "remote_repo_path": self.sshRemoteRepoPathEdit,
    },
    "aws": lambda self: {
        "region": self.awsRegionEdit,
        "ami_id": self.awsAmiIdEdit,
        "instance_type": self.awsInstanceTypeEdit,
        "instance_name": self.awsInstanceNameEdit,
        "security_group": self.awsSecurityGroupEdit,
        "key_name": self.awsKeyNameEdit,
        "remote_path": self.awsRemotePathEdit,
    },
}


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
        self._model_entries_by_id = {}

        cleanup_old_temp_dirs()

        self.selectAllButton.clicked.connect(self.on_select_all_layers)
        self.layersList.itemChanged.connect(self.update_selection_state)

        self.newChartButton.clicked.connect(self.open_chart_builder)
        self.selectChartFolderButton.clicked.connect(self.select_chart_folder)
        self.clearChartFolderButton.clicked.connect(self.clear_chart_folder)
        self.selectAllChartsButton.clicked.connect(lambda: self.toggle_all_checked(self.chartFilesList))

        self.refreshModelsButton.clicked.connect(self.refresh_models_list)
        self.selectModelFolderButton.clicked.connect(self.select_model_folder)
        self.clearModelFolderButton.clicked.connect(self.clear_model_folder)
        self.selectAllModelsButton.clicked.connect(lambda: self.toggle_all_checked(self.modelFilesList))

        self.radioGenerate.toggled.connect(self.update_action_stack)
        self.radioDeploy.toggled.connect(self.update_action_stack)
        self.selectOutputFolderButton.clicked.connect(self.select_output_folder)

        self.radioLocal.toggled.connect(self.update_deploy_stack)
        self.radioSSH.toggled.connect(self.update_deploy_stack)
        self.radioAWS.toggled.connect(self.update_deploy_stack)

        self.historyList.itemSelectionChanged.connect(self.update_history_buttons_state)
        self.historyOpenAppButton.clicked.connect(self.on_history_open_app)
        self.historyRestoreButton.clicked.connect(self.on_history_restore)
        self.historyViewLogButton.clicked.connect(self.on_history_view_log)
        self.historyGroup.toggled.connect(self.on_history_group_toggled)

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
        QgsProject.instance().readProject.connect(self.on_project_read)

        self.load_layers()
        self.refresh_models_list()
        self.load_history()
        self.restore_selection_from_project()
        self.check_requirements()

    def on_project_read(self):
        """A different (or the same) project was opened — reload everything that's
        project-scoped: layers, project-embedded models, and the saved selection."""
        self.load_layers()
        self.refresh_models_list()
        self.restore_selection_from_project()

    def closeEvent(self, event):
        self.save_current_selection()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Generic checkable-list helpers (layers / chart files / model files)
    # ------------------------------------------------------------------

    def toggle_all_checked(self, list_widget):
        count = list_widget.count()
        if count == 0:
            return

        all_checked = all(
            list_widget.item(i).checkState() == Qt.CheckState.Checked for i in range(count)
        )
        new_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked

        for i in range(count):
            list_widget.item(i).setCheckState(new_state)

    def get_checked_texts(self, list_widget):
        return [
            list_widget.item(i).text()
            for i in range(list_widget.count())
            if list_widget.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _checked_data(self, list_widget):
        return {
            list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(list_widget.count())
            if list_widget.item(i).checkState() == Qt.CheckState.Checked
        }

    def populate_file_list(self, list_widget, folder):
        list_widget.clear()
        try:
            entries = sorted(os.listdir(folder))
        except OSError:
            entries = []

        for name in entries:
            item = QListWidgetItem(name)
            item.setCheckState(Qt.CheckState.Checked)
            list_widget.addItem(item)

    # ------------------------------------------------------------------
    # Layers
    # ------------------------------------------------------------------

    def load_layers(self):
        # Preserve the user's check state across a live layersAdded/layersRemoved
        # refresh instead of resetting everything back to "all checked".
        had_items = self.layersList.count() > 0
        previously_checked = self._checked_data(self.layersList)

        self.layersList.clear()

        project = QgsProject.instance()
        layers = project.mapLayers().values()

        for layer in layers:
            if layer.type() not in (QgsMapLayer.LayerType.VectorLayer, QgsMapLayer.LayerType.RasterLayer):
                continue

            item = QListWidgetItem(layer.name())
            item.setData(Qt.ItemDataRole.UserRole, layer.id())
            if had_items:
                item.setCheckState(Qt.CheckState.Checked if layer.id() in previously_checked else Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Checked)

            self.layersList.addItem(item)

        self.update_selection_state()

    def on_select_all_layers(self):
        self.toggle_all_checked(self.layersList)
        self.update_selection_state()

    def update_selection_state(self):
        has_selected = any(
            self.layersList.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.layersList.count())
        )
        self.infoLabel.setVisible(not has_selected)
        self._apply_chart_validation_icons()

    def get_selected_layers(self):
        project = QgsProject.instance()
        selected_layers = []

        for i in range(self.layersList.count()):
            item = self.layersList.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                layer = project.mapLayer(item.data(Qt.ItemDataRole.UserRole))
                if layer:
                    selected_layers.append(layer)

        return selected_layers

    def get_selected_vector_layers(self):
        return [layer for layer in self.get_selected_layers() if layer.type() == QgsMapLayer.LayerType.VectorLayer]

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------

    def select_chart_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select charts folder", "")
        if folder:
            self.selected_chart_folder = folder
            self.chartFolderPathLabel.setText(folder)
            self.populate_file_list(self.chartFilesList, folder)
            self._apply_chart_validation_icons()

    def clear_chart_folder(self):
        self.selected_chart_folder = None
        self.chartFolderPathLabel.setText("No folder selected")
        self.chartFilesList.clear()

    def get_selected_chart_items(self):
        if not self.selected_chart_folder:
            return None
        return self.get_checked_texts(self.chartFilesList)

    def open_chart_builder(self):
        vector_layers = self.get_selected_vector_layers()
        if not vector_layers:
            vector_layers = [
                layer for layer in QgsProject.instance().mapLayers().values()
                if layer.type() == QgsMapLayer.LayerType.VectorLayer
            ]
        if not vector_layers:
            QMessageBox.warning(
                self, "No vector layers",
                "Add a vector layer to the project before building a chart.",
            )
            return

        default_base_url = "http://localhost:8080"
        if self.radioDeploy.isChecked():
            if self.radioLocal.isChecked() and self.localHostEdit.text().strip():
                default_base_url = self.localHostEdit.text().strip()
            elif self.radioSSH.isChecked() and self.sshHostEdit.text().strip():
                default_base_url = self.sshHostEdit.text().strip()

        existing_names = set()
        if self.selected_chart_folder and os.path.isdir(self.selected_chart_folder):
            existing_names = {
                os.path.splitext(n)[0]
                for n in os.listdir(self.selected_chart_folder)
                if n.lower().endswith(".json")
            }

        dialog = ChartBuilderDialog(
            vector_layers, default_base_url, self.selected_chart_folder, existing_names, parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved_chart_filename:
            if not self.selected_chart_folder:
                self.selected_chart_folder = dialog.saved_chart_folder
                self.chartFolderPathLabel.setText(self.selected_chart_folder)
            self.populate_file_list(self.chartFilesList, self.selected_chart_folder)
            self._apply_chart_validation_icons()
            for i in range(self.chartFilesList.count()):
                item = self.chartFilesList.item(i)
                if item.text() == dialog.saved_chart_filename:
                    item.setCheckState(Qt.CheckState.Checked)

    def _apply_chart_validation_icons(self):
        """Mark each chart file with a warning icon/tooltip when it looks like it
        won't render against the currently selected layers."""
        if not self.selected_chart_folder or self.chartFilesList.count() == 0:
            return

        vector_layers = self.get_selected_vector_layers()
        basenames = [naming.layer_source_basename(layer) for layer in vector_layers]
        fields_by_basename = {
            naming.layer_source_basename(layer): {naming.attribute_name(f.name()) for f in layer.fields()}
            for layer in vector_layers
        }
        warning_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)

        for i in range(self.chartFilesList.count()):
            item = self.chartFilesList.item(i)
            name = item.text()
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(self.selected_chart_folder, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
            except OSError:
                continue

            issues = chart_builder.validate_chart_spec(raw_text, basenames, fields_by_basename)
            if issues:
                item.setIcon(warning_icon)
                item.setToolTip("\n".join(issues))
            else:
                item.setIcon(QIcon())
                item.setToolTip("")

    def _validate_checked_charts(self, selected_layers):
        """Blocking (confirm-to-proceed) check run before Generate/Deploy: warns
        about any *checked* chart file that looks like it won't render correctly."""
        if not self.selected_chart_folder:
            return True

        vector_layers = [layer for layer in selected_layers if layer.type() == QgsMapLayer.LayerType.VectorLayer]
        basenames = [naming.layer_source_basename(layer) for layer in vector_layers]
        fields_by_basename = {
            naming.layer_source_basename(layer): {naming.attribute_name(f.name()) for f in layer.fields()}
            for layer in vector_layers
        }

        problems = []
        for i in range(self.chartFilesList.count()):
            item = self.chartFilesList.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            name = item.text()
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(self.selected_chart_folder, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
            except OSError:
                continue
            issues = chart_builder.validate_chart_spec(raw_text, basenames, fields_by_basename)
            if issues:
                problems.append((name, issues))

        if not problems:
            return True

        lines = []
        for name, issues in problems:
            lines.append(f"{name}:")
            lines.extend(f"    - {issue}" for issue in issues)

        reply = QMessageBox.warning(
            self,
            "Chart validation issues",
            "The following selected chart(s) look like they won't render correctly:\n\n"
            + "\n".join(lines)
            + "\n\nContinue anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    def refresh_models_list(self):
        had_items = self.modelFilesList.count() > 0
        previously_checked = self._checked_data(self.modelFilesList)

        entries = model_discovery.discover_all_models(extra_folder=self.selected_model_folder)
        self._model_entries_by_id = {entry.id: entry for entry in entries}

        self.modelFilesList.clear()
        for entry in entries:
            item = QListWidgetItem(f"{entry.display_name}  ({entry.source})")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            tooltip_parts = [p for p in (entry.parameter_summary(), entry.source_file_path) if p]
            item.setToolTip("\n".join(tooltip_parts))
            if had_items:
                item.setCheckState(Qt.CheckState.Checked if entry.id in previously_checked else Qt.CheckState.Unchecked)
            else:
                item.setCheckState(Qt.CheckState.Checked)
            self.modelFilesList.addItem(item)

    def select_model_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select extra models folder", "")
        if folder:
            self.selected_model_folder = folder
            self.modelFolderPathLabel.setText(folder)
            self.refresh_models_list()

    def clear_model_folder(self):
        self.selected_model_folder = None
        self.modelFolderPathLabel.setText("No extra folder selected")
        self.refresh_models_list()

    def get_selected_model_entries(self):
        selected = []
        for i in range(self.modelFilesList.count()):
            item = self.modelFilesList.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                entry = self._model_entries_by_id.get(item.data(Qt.ItemDataRole.UserRole))
                if entry:
                    selected.append(entry)
        return selected

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
            self.awsSecretAccessKeyEdit: "AWS IAM secret access key matching the access key above.",  # pragma: allowlist secret
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

        self.dataTabs.setTabIcon(0, style.standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.dataTabs.setTabIcon(1, style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.dataTabs.setTabIcon(2, style.standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))

        self.selectChartFolderButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.selectModelFolderButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.selectOutputFolderButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))

        self.clearChartFolderButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        self.clearModelFolderButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
        self.refreshModelsButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))

        self.installGispubButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.refreshStatusButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))

        self.runButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.cancelButton.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))

    def add_browse_action(self, line_edit, dialog_title):
        """Add a clickable folder icon inside a QLineEdit to browse for a file."""
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        action = QAction(icon, dialog_title, line_edit)
        action.triggered.connect(lambda: self.browse_for_file(line_edit, dialog_title))
        line_edit.addAction(action, QLineEdit.ActionPosition.TrailingPosition)

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
    # Deploy history
    # ------------------------------------------------------------------

    def load_history(self):
        self.historyList.clear()
        records = state_store.load_deploy_history()
        for record in reversed(records):  # most recent first
            summary = f"{record.get('timestamp', '')}  [{record.get('deploy_type', '')}]"
            exit_code = record.get("exit_code")
            summary += "  ✔" if exit_code == 0 else f"  ✖ (exit {exit_code})"
            if record.get("host"):
                summary += f"  → {record['host']}"

            item = QListWidgetItem(summary)
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.historyList.addItem(item)

        self.update_history_buttons_state()

    def update_history_buttons_state(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.historyOpenAppButton.setEnabled(bool(record and record.get("host")))
        self.historyRestoreButton.setEnabled(record is not None)
        self.historyViewLogButton.setEnabled(bool(record and record.get("log_tail")))

    def on_history_group_toggled(self, checked):
        self.historyList.setVisible(checked)
        self.historyOpenAppButton.setVisible(checked)
        self.historyRestoreButton.setVisible(checked)
        self.historyViewLogButton.setVisible(checked)

    def on_history_open_app(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if record and record.get("host"):
            QDesktopServices.openUrl(QUrl(record["host"]))

    def on_history_restore(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:
            return

        deploy_type = record.get("deploy_type", "local")
        self.radioDeploy.setChecked(True)
        {"local": self.radioLocal, "ssh": self.radioSSH, "aws": self.radioAWS}.get(
            deploy_type, self.radioLocal
        ).setChecked(True)

        widgets = _RESTORE_FIELD_WIDGETS.get(deploy_type, lambda self: {})(self)
        for key, widget in widgets.items():
            value = record.get("restorable_fields", {}).get(key)
            if value is None:
                continue
            if hasattr(widget, "setValue"):
                try:
                    widget.setValue(int(value))
                except (TypeError, ValueError):
                    pass
            else:
                widget.setText(str(value))

        QMessageBox.information(
            self,
            "Settings restored",
            "Non-secret deploy fields were restored from this run. "
            "Credentials and key paths are never stored — please re-enter them.",
        )

    def on_history_view_log(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:
            return

        box = QMessageBox(self)
        box.setWindowTitle("Deploy log")
        box.setText(f"{record.get('timestamp', '')} — {record.get('deploy_type', '')}")
        box.setDetailedText("\n".join(record.get("log_tail") or []) or "(no log captured)")
        box.exec()

    # ------------------------------------------------------------------
    # Persistence (per-project selection)
    # ------------------------------------------------------------------

    def save_current_selection(self):
        project = QgsProject.instance()
        selection = {
            "layer_ids": [
                self.layersList.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.layersList.count())
                if self.layersList.item(i).checkState() == Qt.CheckState.Checked
            ],
            "model_ids": [
                self.modelFilesList.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.modelFilesList.count())
                if self.modelFilesList.item(i).checkState() == Qt.CheckState.Checked
            ],
            "chart_folder": self.selected_chart_folder or "",
            "chart_files": self.get_selected_chart_items(),
            "model_folder": self.selected_model_folder or "",
            "output_dir": self.output_dir or "",
            "action": "deploy" if self.radioDeploy.isChecked() else "generate",
            "deploy_type": self.current_deploy_type(),
        }
        state_store.save_project_selection(project, selection)

    def restore_selection_from_project(self):
        project = QgsProject.instance()
        if not state_store.has_saved_selection(project):
            return  # nothing saved yet — keep the "everything selected" default

        selection = state_store.load_project_selection(project)

        layer_ids = set(selection["layer_ids"])
        for i in range(self.layersList.count()):
            item = self.layersList.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in layer_ids else Qt.CheckState.Unchecked)
        self.update_selection_state()

        if selection["chart_folder"] and os.path.isdir(selection["chart_folder"]):
            self.selected_chart_folder = selection["chart_folder"]
            self.chartFolderPathLabel.setText(self.selected_chart_folder)
            self.populate_file_list(self.chartFilesList, self.selected_chart_folder)
            if selection["chart_files"] is not None:
                chart_files = set(selection["chart_files"])
                for i in range(self.chartFilesList.count()):
                    item = self.chartFilesList.item(i)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in chart_files else Qt.CheckState.Unchecked)
            self._apply_chart_validation_icons()

        if selection["model_folder"] and os.path.isdir(selection["model_folder"]):
            self.selected_model_folder = selection["model_folder"]
            self.modelFolderPathLabel.setText(self.selected_model_folder)
            self.refresh_models_list()

        model_ids = set(selection["model_ids"])
        for i in range(self.modelFilesList.count()):
            item = self.modelFilesList.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in model_ids else Qt.CheckState.Unchecked)

        if selection["output_dir"] and os.path.isdir(selection["output_dir"]):
            self.output_dir = selection["output_dir"]
            self.outputFolderLabel.setStyleSheet("")
            self.outputFolderLabel.setText(self.output_dir)

        self.radioDeploy.setChecked(selection["action"] == "deploy")
        self.radioGenerate.setChecked(selection["action"] != "deploy")

        deploy_type = selection.get("deploy_type", "local")
        {"local": self.radioLocal, "ssh": self.radioSSH, "aws": self.radioAWS}.get(
            deploy_type, self.radioLocal
        ).setChecked(True)

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

        if not self._validate_checked_charts(selected_layers):
            return

        self.save_current_selection()

        if self.radioGenerate.isChecked():
            self.run_generate(selected_layers)
        else:
            self.run_deploy(selected_layers)

    def run_generate(self, selected_layers):
        if not self.output_dir:
            QMessageBox.warning(self, "Output folder required", "Select an output folder before generating.")
            return

        progress_dialog = ProgressDialog(title="Generating...", parent=self)
        progress_dialog.show()

        self.runner = GISPublisherRunner(
            layers=selected_layers,
            output_dir=self.output_dir,
            chart_folder=self.selected_chart_folder,
            chart_items=self.get_selected_chart_items(),
            model_entries=self.get_selected_model_entries(),
            progress_label=progress_dialog.statusLabel,
            progress_bar=progress_dialog.progressBar,
            output_text=progress_dialog.outputText,
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
        progress_dialog.show()

        self.runner = GISPublisherRunner(
            layers=selected_layers,
            output_dir=None,
            chart_folder=self.selected_chart_folder,
            chart_items=self.get_selected_chart_items(),
            model_entries=self.get_selected_model_entries(),
            progress_label=progress_dialog.statusLabel,
            progress_bar=progress_dialog.progressBar,
            output_text=progress_dialog.outputText,
            parent=self,
            debug=self.DEBUG,
            finished_callback=lambda: self.on_deploy_finished(
                progress_dialog, config_path, deploy_type, fields, len(selected_layers)
            ),
        )
        progress_dialog.closeButton.clicked.connect(self.runner.cancel)

        try:
            self.runner.start(config_path=config_path)
        except Exception as e:
            progress_dialog.close()
            os.remove(config_path)
            QMessageBox.critical(self, "Error", str(e))

    def on_deploy_finished(self, progress_dialog, config_path, deploy_type, fields, layer_count):
        progress_dialog.set_finished_state()
        progress_dialog.closeButton.clicked.disconnect()
        progress_dialog.closeButton.clicked.connect(progress_dialog.close)
        if not self.DEBUG:
            progress_dialog.close()
        os.remove(config_path)

        chart_count = len(self.get_selected_chart_items() or [])
        model_count = len(self.get_selected_model_entries())
        project = QgsProject.instance()

        state_store.append_deploy_record(
            project_title=project.title() or project.baseName(),
            deploy_type=deploy_type,
            host=self.runner.resulting_host or fields.get("host", ""),
            layer_count=layer_count,
            chart_count=chart_count,
            model_count=model_count,
            exit_code=getattr(self.runner, "exit_code", -1),
            duration_seconds=self.runner.duration_seconds(),
            log_lines=self.runner.log_lines,
            deploy_fields=fields,
        )
        self.load_history()
