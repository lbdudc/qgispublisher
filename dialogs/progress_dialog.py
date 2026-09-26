"""Progress window of a Generate/Deploy run.

Shows the run as a list of steps (what is done, what is running, what is next)
instead of the raw docker/CLI output, which stays one click away under "Show
details". The window only *renders* the current job of a `PublishJobManager`:
hiding it ("Run in background") or closing it never stops the run.
"""

import os

from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QFont, QTextCursor
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import QgsSettings

from ..core import deploy_errors, deploy_progress as dp

_SHOW_LOG_SETTING = "GISPublisher/showLog"
_MAX_LOG_LINES = 5000
# Steps during which the latest output line says something useful about progress
_STEPS_WITH_ACTIVITY = {"build", "prepare", "upload", "instance", "package"}

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_GREEN, _RED, _AMBER, _BLUE, _GRAY = "#2e7d32", "#c62828", "#b26a00", "#1565c0", "#8a8a8a"

_ICONS = {
    dp.PENDING: ("○", _GRAY),
    dp.DONE: ("✔", _GREEN),
    dp.FAILED: ("✖", _RED),
    dp.SKIPPED: ("–", _GRAY),
}


def _elide(text, limit=90):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _StepRow:
    """The four labels of one step: icon, name, detail, duration."""

    def __init__(self, grid, row):
        self.icon = QLabel()
        self.icon.setFixedWidth(22)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel()
        self.detail = QLabel()
        self.detail.setStyleSheet(f"color: {_GRAY};")
        self.duration = QLabel()
        self.duration.setStyleSheet(f"color: {_GRAY};")
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for column, widget in enumerate((self.icon, self.name, self.detail, self.duration)):
            grid.addWidget(widget, row, column)

    def widgets(self):
        return (self.icon, self.name, self.detail, self.duration)


class ProgressDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("GISPublisher")
        self.setMinimumWidth(560)
        self._rows = []
        self._spinner_index = 0

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.headline = QLabel()
        font = QFont(self.headline.font())
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.headline.setFont(font)
        self.headline.setWordWrap(True)
        root.addWidget(self.headline)

        self.subline = QLabel()
        self.subline.setStyleSheet(f"color: {_GRAY};")
        root.addWidget(self.subline)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        root.addWidget(self.bar)

        steps_frame = QFrame()
        self.steps_grid = QGridLayout(steps_frame)
        self.steps_grid.setContentsMargins(4, 6, 4, 6)
        self.steps_grid.setHorizontalSpacing(8)
        self.steps_grid.setVerticalSpacing(6)
        self.steps_grid.setColumnStretch(2, 1)
        root.addWidget(steps_frame)

        self.services_label = QLabel()
        self.services_label.setWordWrap(True)
        self.services_label.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.services_label)

        # Outcome panel (success / failure / cancelled)
        self.result_frame = QFrame()
        result_layout = QVBoxLayout(self.result_frame)
        self.result_title = QLabel()
        title_font = QFont(self.result_title.font())
        title_font.setBold(True)
        self.result_title.setFont(title_font)
        self.result_title.setWordWrap(True)
        self.result_text = QLabel()
        self.result_text.setWordWrap(True)
        self.result_text.setTextFormat(Qt.TextFormat.RichText)
        self.result_text.setOpenExternalLinks(True)
        self.result_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        result_layout.addWidget(self.result_title)
        result_layout.addWidget(self.result_text)
        result_buttons = QHBoxLayout()
        self.open_app_button = QPushButton("Open app")
        self.copy_link_button = QPushButton("Copy link")
        self.open_folder_button = QPushButton("Open folder")
        for button in (self.open_app_button, self.copy_link_button, self.open_folder_button):
            result_buttons.addWidget(button)
        result_buttons.addStretch(1)
        result_layout.addLayout(result_buttons)
        root.addWidget(self.result_frame)

        # Raw output, hidden until asked for
        details_row = QHBoxLayout()
        self.details_check = QCheckBox("Show details")
        self.copy_log_button = QPushButton("Copy log")
        details_row.addWidget(self.details_check)
        details_row.addStretch(1)
        details_row.addWidget(self.copy_log_button)
        root.addLayout(details_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(_MAX_LOG_LINES)
        self.log_view.setMinimumHeight(180)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(mono)
        root.addWidget(self.log_view)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.background_button = QPushButton("Run in background")
        self.background_button.setToolTip(
            "Hide this window. The run continues; it is listed in the QGIS task manager "
            "and you are notified when it ends."
        )
        self.cancel_button = QPushButton("Cancel")
        buttons.addWidget(self.background_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        show_log = QgsSettings().value(_SHOW_LOG_SETTING, False, type=bool)
        self.details_check.setChecked(show_log)
        self.log_view.setVisible(show_log)
        self.copy_log_button.setVisible(show_log)

        self.details_check.toggled.connect(self._on_details_toggled)
        self.copy_log_button.clicked.connect(self._copy_log)
        self.background_button.clicked.connect(self.hide)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.open_app_button.clicked.connect(self._open_app)
        self.copy_link_button.clicked.connect(self._copy_link)
        self.open_folder_button.clicked.connect(self._open_folder)

        manager.changed.connect(self.refresh)
        manager.logAppended.connect(self._on_log)
        manager.jobStarted.connect(self._on_job_started)

        # Elapsed time + spinner
        self._ticker = QTimer(self)
        self._ticker.setInterval(150)
        self._ticker.timeout.connect(self._tick)

        self.refresh()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        self._reload_log()
        self.refresh()
        self._ticker.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._ticker.stop()

    def _on_job_started(self):
        self._reload_log()
        self.log_view.setVisible(self.details_check.isChecked())
        self.refresh()

    def _on_log(self, line):
        if self.isVisible():
            self.log_view.appendPlainText(line)

    def _reload_log(self):
        self.log_view.clear()
        job = self.manager.job
        if job is not None and job.log_lines:
            self.log_view.setPlainText("\n".join(job.log_lines[-_MAX_LOG_LINES:]))
            self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _on_details_toggled(self, checked):
        self.log_view.setVisible(checked)
        self.copy_log_button.setVisible(checked)
        QgsSettings().setValue(_SHOW_LOG_SETTING, checked)
        self.adjustSize()

    def _copy_log(self):
        job = self.manager.job
        QApplication.clipboard().setText("\n".join(job.log_lines) if job else "")

    def _on_cancel_clicked(self):
        job = self.manager.job
        if job is not None and not job.finished:
            self.cancel_button.setEnabled(False)
            self.manager.cancel()
        else:
            self.hide()

    def _open_app(self):
        job = self.manager.job
        if job is not None and job.url:
            QDesktopServices.openUrl(QUrl(job.url))

    def _copy_link(self):
        job = self.manager.job
        if job is not None and job.url:
            QApplication.clipboard().setText(job.url)

    def _open_folder(self):
        job = self.manager.job
        if job is not None and job.zip_file and os.path.isfile(job.zip_file):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(job.zip_file)))
        elif job is not None and job.output_dir and os.path.isdir(job.output_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.output_dir))

    def _tick(self):
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER)
        job = self.manager.job
        if job is None:
            return
        if not job.finished:
            self.subline.setText(self._subline_text(job))
            for step, row in zip(job.progress.steps, self._rows):
                if step.status == dp.RUNNING:
                    row.icon.setText(_SPINNER[self._spinner_index])
                    # Output lines don't trigger a full render, so pick up the
                    # latest one here
                    row.detail.setText(self._step_detail(job, step))

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _ensure_rows(self, count):
        while len(self._rows) < count:
            self._rows.append(_StepRow(self.steps_grid, len(self._rows)))
        for index, row in enumerate(self._rows):
            for widget in row.widgets():
                widget.setVisible(index < count)

    @staticmethod
    def _step_detail(job, step):
        if step.status == dp.RUNNING:
            if step.id == "wait":
                ready, total, waiting = job.progress.services_summary()
                if total:
                    text = f"{ready}/{total} services ready"
                    return text + (f" · waiting for {', '.join(waiting[:2])}" if waiting else "")
                return "starting services…"
            if step.id in ("export", "stage"):
                return _elide(job.status_text)
            if step.id in _STEPS_WITH_ACTIVITY and job.last_log:
                return _elide(job.last_log)
            return ""
        if step.status == dp.FAILED:
            # The reason (Docker's "Bind for ... failed"), not the command line
            # short: the result panel below carries the full explanation
            return _elide(deploy_errors.last_error_line(step.detail.splitlines()), 55)
        if step.status == dp.SKIPPED:
            return _elide(step.detail)
        return ""

    @staticmethod
    def _subline_text(job):
        elapsed = dp.format_duration(job.duration if job.duration is not None else job.progress.elapsed())
        if job.finished:
            return f"Finished in {elapsed}"
        if job.cancelled or job.status_text == "Cancelling...":
            return f"Cancelling… · {elapsed}"
        current = job.progress.current
        label = current.label if current else job.status_text
        return f"{label}… · {elapsed}" if label else elapsed

    def refresh(self):
        job = self.manager.job
        if job is None:
            self.headline.setText("GISPublisher")
            self.subline.setText("Nothing is running.")
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self._ensure_rows(0)
            self.services_label.setVisible(False)
            self.result_frame.setVisible(False)
            self.background_button.setVisible(False)
            self.cancel_button.setText("Close")
            self.cancel_button.setEnabled(True)
            return

        self.setWindowTitle(f"GISPublisher — {job.verb}")
        self.headline.setText(job.headline)
        self.subline.setText(self._subline_text(job))

        # Steps
        steps = job.progress.steps
        self._ensure_rows(len(steps))
        for step, row in zip(steps, self._rows):
            if step.status == dp.RUNNING:
                glyph, color = _SPINNER[self._spinner_index], _BLUE
            else:
                glyph, color = _ICONS.get(step.status, _ICONS[dp.PENDING])
            row.icon.setText(glyph)
            row.icon.setStyleSheet(f"color: {color}; font-weight: bold;")
            row.name.setText(step.label)
            weight = "bold" if step.status == dp.RUNNING else "normal"
            dim = f"color: {_GRAY};" if step.status in (dp.PENDING, dp.SKIPPED) else ""
            row.name.setStyleSheet(f"font-weight: {weight}; {dim}")
            row.detail.setText(self._step_detail(job, step))
            row.detail.setStyleSheet(f"color: {_RED if step.status == dp.FAILED else _GRAY};")
            if step.duration_ms is not None and step.status in (dp.DONE, dp.FAILED):
                row.duration.setText(dp.format_duration(step.duration_ms / 1000))
            else:
                row.duration.setText("")

        # Bar: measured by steps once the CLI announced them, busy before that
        fraction = job.progress.smooth_fraction
        if job.finished:
            self.bar.setRange(0, 100)
            self.bar.setValue(100 if job.ok else int((job.progress.fraction or 0) * 100))
        elif fraction is None or not job.progress.cli_reported:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(fraction * 100))

        self._render_services(job)
        self._render_result(job)

        finished = job.finished
        self.background_button.setVisible(not finished)
        self.cancel_button.setText("Close" if finished else "Cancel")
        self.cancel_button.setEnabled(finished or not job.cancelled and job.status_text != "Cancelling...")

    def _render_services(self, job):
        services = job.progress.services
        if not services:
            self.services_label.setVisible(False)
            return
        colors = {"ready": _GREEN, "pending": _AMBER, "failed": _RED}
        chips = "&nbsp;&nbsp; ".join(
            f'<span style="color:{colors.get(s.get("status"), _GRAY)}">●</span> {s.get("name", "?")}'
            for s in services
        )
        self.services_label.setText(chips)
        self.services_label.setVisible(True)

    def _render_result(self, job):
        if not job.finished:
            self.result_frame.setVisible(False)
            return

        if job.cancelled:
            tone, title, text = _GRAY, "Cancelled", "The run was stopped before it finished."
        elif job.ok:
            tone = _AMBER if job.warnings else _GREEN
            done = {"deploy": "Deployed", "update": "Data updated"}.get(job.kind, "Generated")
            title = f"{done} successfully" if not job.warnings else f"{done} with warnings"
            parts = []
            if job.zip_file:
                parts.append(f"Zip saved to {job.zip_file}")
            elif job.url:
                parts.append(f'Available at <a href="{job.url}">{job.url}</a>')
            elif job.kind == "generate" and job.output_dir:
                parts.append(f"Written to {job.output_dir}")
            if job.edit_account:
                user, password = job.edit_account
                parts.append(
                    f"Editing account (to change data in the app): user <b>{user}</b>, password "
                    f"<b>{password}</b> <span style='color:{_GRAY}'>(kept in the deployment folder)</span>"
                )
            if job.warnings:
                names = ", ".join(name for name, _message in job.warnings[:6])
                more = "…" if len(job.warnings) > 6 else ""
                parts.append(f"{len(job.warnings)} layer(s) were not published: {names}{more}")
            text = "<br>".join(parts)
        else:
            tone, title = _RED, job.failure_title
            text = job.failure_hint
            if job.failure_detail:
                text += f"<br><span style='color:{_GRAY}'>{_elide(job.failure_detail, 160)}</span>"

        self.result_frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {tone}; border-radius: 6px; }} QLabel {{ border: none; }}"
        )
        self.result_title.setText(title)
        self.result_title.setStyleSheet(f"color: {tone}; border: none;")
        self.result_text.setText(text)
        self.result_text.setVisible(bool(text))
        has_url = job.ok and bool(job.url)
        self.open_app_button.setVisible(has_url)
        self.copy_link_button.setVisible(has_url)
        self.open_folder_button.setVisible(
            (bool(job.zip_file) and os.path.isfile(job.zip_file))
            or (bool(job.output_dir) and os.path.isdir(job.output_dir))
        )
        self.result_frame.setVisible(True)

        if not job.ok and not job.cancelled and not self.details_check.isChecked():
            # A failure is what the log is for: show it, without persisting the choice
            self.details_check.blockSignals(True)
            self.details_check.setChecked(True)
            self.details_check.blockSignals(False)
            self.log_view.setVisible(True)
            self.copy_log_button.setVisible(True)
