"""The Generate/Deploy run as a background job.

`PublishJobManager` is created once, by the plugin, and outlives the main dialog
and the progress window: closing either never stops a run. While a job runs it
shows up in QGIS's task manager (status bar) with its progress and can be
cancelled from there, and when it ends a message-bar notification says how it
went (unless the progress window is open and already shows it).

Only the CLI part of a run is truly concurrent (it is a QProcess); staging the
layers has to read QGIS layers and therefore happens on the GUI thread, though it
repaints between layers (see GISPublisherRunner.start).
"""

import os

from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QApplication, QPushButton
from qgis.core import Qgis, QgsApplication, QgsMessageLog

from . import deploy_errors, deploy_progress

_LOG_TAG = "GISPublisher"
_LOG_TAIL_FOR_DIAGNOSIS = 60


def _level(name):
    """Qgis.MessageLevel.<name> across the QGIS versions that expose it as a
    scoped or as a plain enum."""
    scoped = getattr(Qgis, "MessageLevel", None)
    return getattr(scoped, name, None) if scoped is not None and hasattr(scoped, name) else getattr(Qgis, name)


class PublishJob:
    """State of one run. Plain data + the runner; no widgets."""

    def __init__(self, runner, kind, title, target, on_finished=None):
        self.runner = runner
        self.kind = kind  # "generate" | "deploy"
        self.title = title  # app name
        self.target = target  # "Local Docker", "SSH server", ...
        self.on_finished = on_finished
        self.progress = deploy_progress.DeployProgress()
        self.progress.set_local_steps(runner.LOCAL_STEPS)
        self.status_text = ""
        self.last_log = ""  # most recent output line, shown next to a running step
        self.duration = None  # seconds, set when the run ends
        self.finished = False
        self.cancelled = False
        self.ok = False
        self.exit_code = None
        self.failure_title = ""
        self.failure_hint = ""
        self.failure_detail = ""
        self.warnings = []  # (layer, message) for layers that weren't published
        self.task = None

    @property
    def verb(self):
        return "Deploying" if self.kind == "deploy" else "Generating"

    @property
    def headline(self):
        where = f" → {self.target}" if self.target else ""
        return f"{self.verb} {self.title}{where}"

    @property
    def log_lines(self):
        return self.runner.log_lines

    @property
    def url(self):
        return self.progress.url or self.runner.resulting_host

    @property
    def output_dir(self):
        return self.progress.output_dir or self.runner.output_dir or ""


class PublishJobManager(QObject):
    """Owns the (single) active job. UIs listen to its signals and render from
    `job.progress`, so any number of windows can come and go."""

    jobStarted = pyqtSignal()
    changed = pyqtSignal()  # something a UI shows changed: re-render
    logAppended = pyqtSignal(str)
    jobFinished = pyqtSignal()

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.job = None
        self._dialog = None
        self._task_poll = QTimer(self)
        self._task_poll.setInterval(1000)
        self._task_poll.timeout.connect(self._check_task_cancelled)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_running(self):
        return self.job is not None and not self.job.finished

    def start_job(self, runner, kind, title, target, start_kwargs, on_finished=None, show_progress=True):
        """Register `runner` as the active job and start it. Raises whatever
        `runner.start` raises (after cleaning up), so the caller can report it.

        The progress window is opened before `runner.start`, whose first phase
        (staging the layers) is long and runs on this thread."""
        if self.is_running():
            raise RuntimeError("A deployment is already running.")

        job = PublishJob(runner, kind, title, target, on_finished)
        self.job = job
        runner.statusChanged.connect(self._on_status)
        runner.logLine.connect(self._on_log)
        runner.progressEvent.connect(self._on_event)
        runner.finishedRun.connect(self._on_runner_finished)
        self._start_task(job)
        self.jobStarted.emit()
        self.changed.emit()
        if show_progress:
            self.show_progress()
            QApplication.processEvents()

        try:
            runner.start(**start_kwargs)
        except Exception:
            self._abandon(job)
            raise
        return job

    def cancel(self):
        if self.is_running():
            self.job.status_text = "Cancelling..."
            self.job.runner.cancel()
            self.changed.emit()

    def shutdown(self):
        """Plugin unload: stop a running job and release the task."""
        if self.is_running():
            self.job.runner.cancel()
            self._finish_task(self.job, False)
            self.job.finished = True
        self._task_poll.stop()
        if self._dialog is not None:
            self._dialog.close()
            self._dialog.deleteLater()
            self._dialog = None

    def _abandon(self, job):
        """start() failed before the run got going."""
        job.finished = True
        self._finish_task(job, False)
        self.changed.emit()
        self.jobFinished.emit()

    # ------------------------------------------------------------------
    # Runner signals
    # ------------------------------------------------------------------

    def _on_status(self, text):
        if self.job is None:
            return
        self.job.status_text = text
        self.changed.emit()

    def _on_log(self, line):
        if self.job is not None:
            self.job.last_log = line
        self.logAppended.emit(line)

    def _on_event(self, event):
        job = self.job
        if job is None:
            return
        if job.progress.apply(event):
            self._update_task(job)
            self.changed.emit()

    def _on_runner_finished(self, exit_code, cancelled):
        job = self.job
        if job is None or job.finished:
            return
        job.finished = True
        job.exit_code = exit_code
        job.cancelled = cancelled
        job.ok = exit_code == 0 and not cancelled
        job.duration = job.runner.duration_seconds()
        job.warnings = job.runner.failed_export_layers()
        self._mark_unfinished_steps(job)
        if not job.ok and not cancelled:
            self._explain_failure(job)

        self._finish_task(job, job.ok)
        self._log_outcome(job)

        if job.on_finished is not None:
            try:
                job.on_finished(job)
            except Exception as e:  # bookkeeping must never break the notification below
                QgsMessageLog.logMessage(f"Post-run bookkeeping failed: {e}", _LOG_TAG, level=_level("Warning"))

        self.changed.emit()
        if not self._dialog_visible():
            self._notify(job)
        self.jobFinished.emit()

    # ------------------------------------------------------------------
    # Outcome
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_unfinished_steps(job):
        """After a failure the CLI never says anything about the steps it didn't
        reach; a step still `running` (killed process, cancel) would spin forever."""
        for step in job.progress.steps:
            if step.status == deploy_progress.RUNNING:
                step.status = deploy_progress.FAILED if not job.ok else deploy_progress.DONE

    @staticmethod
    def _explain_failure(job):
        error = job.progress.error or {}
        tail = "\n".join(job.log_lines[-_LOG_TAIL_FOR_DIAGNOSIS:])
        explanation = deploy_errors.explain(error.get("message"), error.get("detail"), tail)
        # The reason in the error text (docker's own message, the ssh error...) when
        # there is one, else the last error-looking line of the output
        message_lines = (error.get("message") or "").splitlines()
        last_line = deploy_errors.last_error_line(message_lines) or deploy_errors.last_error_line(job.log_lines)
        if explanation is not None:
            job.failure_title = explanation.title
            job.failure_hint = explanation.hint
        else:
            job.failure_title = f"{job.verb} failed"
            job.failure_hint = "Open the details to see what went wrong."
        job.failure_detail = last_line

    @staticmethod
    def _log_outcome(job):
        if job.ok:
            QgsMessageLog.logMessage(
                f"{job.headline}: finished" + (f" ({job.url})" if job.url else ""), _LOG_TAG, level=_level("Info")
            )
        elif job.cancelled:
            QgsMessageLog.logMessage(f"{job.headline}: cancelled", _LOG_TAG, level=_level("Warning"))
        else:
            QgsMessageLog.logMessage(
                f"{job.headline}: {job.failure_title}. {job.failure_detail}", _LOG_TAG, level=_level("Critical")
            )

    # ------------------------------------------------------------------
    # QGIS task manager
    # ------------------------------------------------------------------

    def _start_task(self, job):
        try:
            from qgis.core import QgsProxyProgressTask

            task = QgsProxyProgressTask(f"GISPublisher: {job.headline}")
            QgsApplication.taskManager().addTask(task)
            job.task = task
            self._task_poll.start()
        except Exception as e:  # the task manager is a convenience, never a requirement
            job.task = None
            QgsMessageLog.logMessage(f"Could not register the QGIS task: {e}", _LOG_TAG, level=_level("Warning"))

    def _update_task(self, job):
        task = job.task
        if task is None:
            return
        fraction = job.progress.fraction
        if fraction is not None:
            task.setProxyProgress(fraction * 100)
        current = job.progress.current
        if current is not None:
            try:
                task.setDescription(f"GISPublisher: {job.headline} — {current.label}")
            except Exception:  # pragma: no cover - older bindings
                pass

    def _finish_task(self, job, ok):
        task, job.task = job.task, None
        self._task_poll.stop()
        if task is not None:
            try:
                task.finalize(bool(ok))
            except Exception:  # pragma: no cover - task already gone
                pass

    def _check_task_cancelled(self):
        """The task manager's cancel button cancels the proxy task; that means
        "stop the run"."""
        job = self.job
        if job is None or job.finished or job.task is None:
            return
        try:
            cancelled = job.task.isCanceled()
        except Exception:  # pragma: no cover
            return
        if cancelled:
            self.cancel()

    # ------------------------------------------------------------------
    # Windows / notifications
    # ------------------------------------------------------------------

    def show_progress(self):
        """Open (or raise) the progress window for the current/last job."""
        from ..dialogs.progress_dialog import ProgressDialog

        if self._dialog is None:
            parent = self.iface.mainWindow() if self.iface is not None else None
            self._dialog = ProgressDialog(self, parent)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _dialog_visible(self):
        return self._dialog is not None and self._dialog.isVisible()

    def _notify(self, job):
        if self.iface is None:
            return
        bar = self.iface.messageBar()
        if job.cancelled:
            bar.pushMessage("GISPublisher", f"{job.headline}: cancelled.", level=_level("Warning"), duration=8)
            return

        if job.ok:
            text = f"{job.title}: {'deployed' if job.kind == 'deploy' else 'generated'} successfully."
            if job.warnings:
                text += f" {len(job.warnings)} layer(s) were not published."
            level = _level("Warning") if job.warnings else _level("Success")
        else:
            text = f"{job.failure_title}. {job.failure_hint}"
            level = _level("Critical")

        item = bar.createMessage("GISPublisher", text)
        if job.ok and job.url:
            item.layout().addWidget(self._button("Open app", lambda: QDesktopServices.openUrl(QUrl(job.url))))
        if job.ok and job.output_dir and os.path.isdir(job.output_dir):
            item.layout().addWidget(
                self._button("Open folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(job.output_dir)))
            )
        item.layout().addWidget(self._button("Details", self.show_progress))
        bar.pushWidget(item, level, 0)

    @staticmethod
    def _button(label, callback):
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False: callback())
        return button
