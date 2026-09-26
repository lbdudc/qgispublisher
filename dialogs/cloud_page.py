from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import cloud_providers, credentials


class _TokenTestThread(QThread):
    """Asks the provider's API something harmless with the token, off the UI thread."""

    result = pyqtSignal(bool, str)

    def __init__(self, deploy_type, token, parent=None):
        super().__init__(parent)
        self.deploy_type = deploy_type
        self.token = token

    def run(self):
        self.result.emit(*cloud_providers.check_token(self.deploy_type, self.token))


def _note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(dark);")
    return label


class CloudProviderPage(QWidget):
    """The deploy page of a provider that rents a server over an API token (Hetzner Cloud,
    DigitalOcean): the token, the server to create, and the optional HTTPS domain.

    ``fields()`` is what ``core.deploy_config`` / ``core.credentials`` read (``token``,
    ``server_name``, ``size``, ``region``, ``ssh_key_path``, ``domain``, ``acme_email``);
    ``set_fields`` takes the non-secret ones back from a saved run. The provider is not tried
    against the real service yet, which the page says.
    """

    changed = pyqtSignal()

    def __init__(self, deploy_type, https_hint="", parent=None):
        super().__init__(parent)
        self.deploy_type = deploy_type
        meta = cloud_providers.PROVIDERS[deploy_type]
        self.setObjectName(f"page_{deploy_type}")
        self._test_thread = None

        self.hintLabel = _note(
            f"Creates a server at {meta['label']} on the first deploy (Ubuntu with Docker installed for you) "
            "and finds it again by its name on the next ones. Not tried yet against the real service."
        )

        self.tokenEdit = QLineEdit()
        self.tokenEdit.setObjectName(f"{deploy_type}TokenEdit")
        self.tokenEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.tokenEdit.setToolTip(f"An API token with write access. Get it at: {meta['token_help']}")
        self.rememberCheck = QCheckBox("Remember the token in the QGIS password manager")
        self.rememberCheck.setObjectName(f"{deploy_type}RememberCheck")
        self.rememberCheck.setToolTip(
            "Stored encrypted by QGIS (it asks for its master password). It is never written to the project or to a file."
        )
        self.testButton = QPushButton("Test token")
        self.testButton.setObjectName(f"{deploy_type}TestTokenButton")
        self.testButton.clicked.connect(self.test_token)

        account = QGroupBox("Account")
        account_form = QFormLayout()
        account_form.addRow("API token", self.tokenEdit)
        account_form.addRow("", self.rememberCheck)
        account_form.addRow("", self.testButton)
        account_layout = QVBoxLayout(account)
        account_layout.addWidget(_note(f"Where to get it: {meta['token_help']}"))
        account_layout.addLayout(account_form)

        self.serverNameEdit = QLineEdit("gispublisher-app")
        self.serverNameEdit.setObjectName(f"{deploy_type}ServerNameEdit")
        self.serverNameEdit.setToolTip(
            "The server's name. If a server with this name already exists it is reused, so the next deploy "
            "goes to the same machine (with its data)."
        )
        self.sizeCombo = self._preset_combo(meta["sizes"], f"{deploy_type}SizeCombo")
        self.sizeCombo.setToolTip("The machine size. The app needs at least 4 GB of memory to build.")
        self.regionCombo = self._preset_combo(meta["regions"], f"{deploy_type}RegionCombo")
        self.regionCombo.setToolTip("Where the server runs.")
        self.sshKeyEdit = QLineEdit()
        self.sshKeyEdit.setObjectName(f"{deploy_type}SshKeyEdit")
        self.sshKeyEdit.setPlaceholderText("~/.ssh/id_ed25519")
        self.sshKeyEdit.setToolTip(
            "Your private ssh key. Its public half (the same name ending in .pub) is added to your account "
            "and lets you in to the server."
        )
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.sshKeyEdit, 1)
        key_row.addWidget(browse)

        server = QGroupBox("Server")
        server_form = QFormLayout(server)
        server_form.addRow("Name", self.serverNameEdit)
        server_form.addRow("Size", self.sizeCombo)
        server_form.addRow("Region", self.regionCombo)
        server_form.addRow("SSH key", key_row)

        self.domainEdit = QLineEdit()
        self.domainEdit.setObjectName(f"{deploy_type}DomainEdit")
        self.domainEdit.setPlaceholderText("gis.example.org")
        self.emailEdit = QLineEdit()
        self.emailEdit.setObjectName(f"{deploy_type}EmailEdit")
        self.emailEdit.setPlaceholderText("you@example.org")
        https = QGroupBox("HTTPS (optional)")
        https_layout = QVBoxLayout(https)
        if https_hint:
            https_layout.addWidget(
                _note(
                    https_hint + " A new server only has an address once it exists, so the certificate is issued "
                    "as soon as you point the name at it."
                )
            )
        https_form = QFormLayout()
        https_form.addRow("Domain", self.domainEdit)
        https_form.addRow("Email", self.emailEdit)
        https_layout.addLayout(https_form)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.hintLabel)
        layout.addWidget(account)
        layout.addWidget(server)
        layout.addWidget(https)
        layout.addStretch(1)

        for edit in (self.tokenEdit, self.serverNameEdit, self.sshKeyEdit, self.domainEdit, self.emailEdit):
            edit.textChanged.connect(self.changed)
        for combo in (self.sizeCombo, self.regionCombo):
            combo.currentTextChanged.connect(self.changed)

    @staticmethod
    def _preset_combo(presets, name):
        """An editable dropdown of ``(value, label)`` presets: the value is what is used, and the
        user can still type another one (a new size or region of the provider)."""
        combo = QComboBox()
        combo.setObjectName(name)
        combo.setEditable(True)
        for value, label in presets:
            combo.addItem(label, value)
        combo.setCurrentIndex(0)
        return combo

    @staticmethod
    def _combo_value(combo):
        """The preset's value when its label is showing, else what was typed."""
        index = combo.findText(combo.currentText())
        return combo.itemData(index) if index >= 0 else combo.currentText().strip()

    @staticmethod
    def _set_combo(combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setEditText(str(value))

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "Private ssh key", self.sshKeyEdit.text())
        if path:
            self.sshKeyEdit.setText(path)

    def fields(self):
        return {
            "token": self.tokenEdit.text(),
            "server_name": self.serverNameEdit.text().strip(),
            "size": self._combo_value(self.sizeCombo),
            "region": self._combo_value(self.regionCombo),
            "ssh_key_path": self.sshKeyEdit.text().strip(),
            "remote_path": "",
            "domain": self.domainEdit.text(),
            "acme_email": self.emailEdit.text(),
        }

    def set_fields(self, fields):
        """Fills in the non-secret fields of a saved run."""
        if fields.get("server_name"):
            self.serverNameEdit.setText(fields["server_name"])
        if fields.get("size"):
            self._set_combo(self.sizeCombo, fields["size"])
        if fields.get("region"):
            self._set_combo(self.regionCombo, fields["region"])
        self.domainEdit.setText(fields.get("domain", ""))
        self.emailEdit.setText(fields.get("acme_email", ""))

    def missing_fields(self, saved_token=False):
        """Labels of the required fields still empty."""
        current = self.fields()
        missing = []
        if not current["token"].strip() and not saved_token:
            missing.append("API token")
        if not current["server_name"]:
            missing.append("Server name")
        if not current["ssh_key_path"]:
            missing.append("SSH key")
        return missing

    # -- the token -----------------------------------------------------

    def token_saved(self):
        """Whether the token will come from the password manager (nothing typed, and saved)."""
        return (
            self.rememberCheck.isChecked()
            and not self.tokenEdit.text().strip()
            and credentials.default_token_store(self.deploy_type).has_saved()
        )

    def resolve_token(self, fields, parent=None):
        """The fields with the token filled in from, or saved to, the password manager as the
        "remember" box says; ``None`` when a saved token cannot be had (the user was told)."""
        store = credentials.default_token_store(self.deploy_type)
        typed = fields.get("token", "").strip()
        if not self.rememberCheck.isChecked():
            if store.has_saved():
                store.forget()
            return fields
        if typed:
            if not store.save("token", typed):
                QMessageBox.warning(
                    parent or self, "Password manager",
                    "The token could not be saved in the QGIS password manager (it stayed locked). "
                    "It is used for this run only.",
                )
            return fields
        loaded = store.load()
        if loaded is None:
            QMessageBox.warning(
                parent or self, "Saved token not available",
                "The saved token could not be read from the QGIS password manager. "
                "Unlock it, or type the token again.",
            )
            return None
        return dict(fields, token=loaded[1])

    def test_token(self):
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        token = self.tokenEdit.text().strip()
        if not token and self.token_saved():
            loaded = credentials.default_token_store(self.deploy_type).load()
            token = loaded[1] if loaded else ""
        if not token:
            QMessageBox.warning(self, "Missing information", "Type the API token before testing it.")
            return
        self.testButton.setEnabled(False)
        self.testButton.setText("Testing…")
        self._test_thread = _TokenTestThread(self.deploy_type, token, self)
        self._test_thread.result.connect(self._on_test_result)
        self._test_thread.start()

    def _on_test_result(self, ok, message):
        self.testButton.setEnabled(True)
        self.testButton.setText("Test token")
        title = f"{cloud_providers.label(self.deploy_type)} token"
        (QMessageBox.information if ok else QMessageBox.warning)(self, title, message)
