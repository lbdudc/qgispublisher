import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..core import state_store

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "ui", "history_dialog.ui")
)


class HistoryDialog(QDialog, FORM_CLASS):
    """Standalone window listing past Generate/Deploy runs — opened from the
    main dialog's History button (previously an inline panel embedded there,
    which either buried the list at the bottom of a long scrollable column or
    pinned it in a way the user didn't like either way — a separate window
    sidesteps both).

    Restoring settings from a record still needs to reach back into the main
    dialog's own fields (app name/output folder, deploy type and its fields),
    so that one action is relayed to the caller via `restore_requested`
    instead of being handled here; everything else (open, view log, clear) is
    fully self-contained in this dialog. `run_again_requested` is the same
    idea for "Run again" — restore fields *and* immediately run, which for
    generate/local-deploy records the caller can do without any further
    input (see `_apply_history_restore`'s `run_again` flag on the receiving
    end); an ssh/aws record has no stored credentials to run with, so the
    caller falls back to restore-only for those.
    """

    restore_requested = pyqtSignal(dict)
    run_again_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.historyList.itemSelectionChanged.connect(self.update_buttons_state)
        self.openButton.clicked.connect(self.on_open)
        self.restoreButton.clicked.connect(self.on_restore)
        self.runAgainButton.clicked.connect(self.on_run_again)
        self.viewLogButton.clicked.connect(self.on_view_log)
        self.clearButton.clicked.connect(self.on_clear)
        self.closeButton.clicked.connect(self.close)

        self.load_history()

    @staticmethod
    def _label(record):
        run_type = record.get("run_type") or "deploy"  # older records predate run_type
        return "generate" if run_type == "generate" else (record.get("deploy_type") or "deploy")

    def load_history(self):
        self.historyList.clear()
        records = state_store.load_run_history()
        for record in reversed(records):  # most recent first
            summary = f"{record.get('timestamp', '')}  [{self._label(record)}]"
            exit_code = record.get("exit_code")
            summary += "  ✔" if exit_code == 0 else f"  ✖ (exit {exit_code})"
            destination = record.get("host") or record.get("output_dir")
            if destination:
                summary += f"  → {destination}"

            item = QListWidgetItem(summary)
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.historyList.addItem(item)

        self.clearButton.setEnabled(self.historyList.count() > 0)
        self.update_buttons_state()

    def update_buttons_state(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.openButton.setEnabled(bool(record and (record.get("host") or record.get("output_dir"))))
        self.restoreButton.setEnabled(record is not None)
        self.runAgainButton.setEnabled(record is not None)
        self.viewLogButton.setEnabled(bool(record and record.get("log_tail")))

    def on_open(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:
            return
        if record.get("host"):
            QDesktopServices.openUrl(QUrl(record["host"]))
        elif record.get("output_dir") and os.path.isdir(record["output_dir"]):
            QDesktopServices.openUrl(QUrl.fromLocalFile(record["output_dir"]))

    def on_restore(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:
            return
        self.restore_requested.emit(record)

    def on_run_again(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:
            return
        # Close first: the run itself happens in the main dialog (its
        # progress dialog would otherwise be layered under this one), and
        # for ssh/aws _apply_history_restore falls back to restore-only, in
        # which case the user needs the main dialog visible to fill in
        # credentials themselves.
        self.close()
        self.run_again_requested.emit(record)

    def on_view_log(self):
        item = self.historyList.currentItem()
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not record:
            return

        # A plain resizable QDialog instead of QMessageBox.setDetailedText(),
        # whose "Show Details" expander renders as a tiny, barely-resizable box
        # — unusable for anything but the shortest log.
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Run log — {record.get('timestamp', '')} ({self._label(record)})")
        dialog.resize(760, 560)

        layout = QVBoxLayout(dialog)
        text_edit = QPlainTextEdit("\n".join(record.get("log_tail") or []) or "(no log captured)")
        text_edit.setReadOnly(True)
        layout.addWidget(text_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

    def on_clear(self):
        if self.historyList.count() == 0:
            return
        reply = QMessageBox.question(
            self,
            "Clear history",
            "Remove all saved run history for this QGIS profile? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        state_store.clear_run_history()
        self.load_history()
