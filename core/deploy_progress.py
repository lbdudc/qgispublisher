"""Progress model of a Generate/Deploy run, independent of Qt so it can be unit
tested outside QGIS.

The gispublisher CLI (run with `--progress json`) prints one `@@gp {...}` line
per event; the plugin adds a few steps of its own (exporting layers...) that
happen before the CLI starts. `DeployProgress` folds both into one list of
steps that the progress dialog, the QGIS task and the notifications render.
"""

import json
import time
from dataclasses import dataclass, field

PROTOCOL_PREFIX = "@@gp "

PENDING = "pending"
RUNNING = "running"
DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"

_FINISHED = (DONE, SKIPPED)


def parse_line(line):
    """The event dict in a `@@gp {...}` line, or None for any other line
    (ordinary CLI output, a malformed payload, a JSON value that isn't an object)."""
    if not line:
        return None
    start = line.find(PROTOCOL_PREFIX)
    if start < 0:
        return None
    try:
        event = json.loads(line[start + len(PROTOCOL_PREFIX):])
    except ValueError:
        return None
    return event if isinstance(event, dict) and "event" in event else None


class LineBuffer:
    """Turns arbitrary output chunks (QProcess delivers them at any byte
    boundary) into complete lines."""

    def __init__(self):
        self._pending = ""

    def feed(self, text):
        self._pending += text
        parts = self._pending.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self._pending = parts.pop()
        return parts

    def flush(self):
        rest, self._pending = self._pending, ""
        return [rest] if rest.strip() else []


@dataclass
class Step:
    id: str
    label: str
    status: str = PENDING
    duration_ms: int = None
    detail: str = ""


@dataclass
class DeployProgress:
    """Ordered steps + live service states + the final outcome of a run."""

    steps: list = field(default_factory=list)
    services: list = field(default_factory=list)
    url: str = ""
    output_dir: str = ""
    # The account that lets people change data in the deployed app (set only when the app
    # has editable layers); it is shown to the user, never logged or saved in the history
    edit_user: str = ""
    edit_password: str = ""
    error: dict = None
    # True once the CLI has announced its own steps; an older CLI never does,
    # and the UI then falls back to an indeterminate bar.
    cli_reported: bool = False
    started_at: float = field(default_factory=time.time)
    _local_ids: tuple = ()

    def set_local_steps(self, steps):
        """Steps the plugin runs itself, before the CLI: [(id, label), ...]."""
        self.steps = [Step(step_id, label) for step_id, label in steps]
        self._local_ids = tuple(step_id for step_id, _ in steps)

    def _find(self, step_id):
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def set_local_status(self, step_id, status, detail=""):
        step = self._find(step_id)
        if step is not None:
            step.status = status
            step.detail = detail

    def apply(self, event):
        """Fold one CLI event in. Returns True when something visible changed."""
        kind = event.get("event")

        if kind == "plan":
            self.cli_reported = True
            known = {s.id: s for s in self.steps}
            local = [s for s in self.steps if s.id in self._local_ids]
            planned = [
                known.get(s["id"]) or Step(s["id"], s.get("label", s["id"]))
                for s in event.get("steps", [])
                if s.get("id") not in self._local_ids
            ]
            self.steps = local + planned
            return True

        if kind == "step":
            self.cli_reported = True
            step = self._find(event.get("id"))
            if step is None:
                step = Step(event["id"], event.get("label", event["id"]))
                self.steps.append(step)
            step.status = event.get("status", step.status)
            step.duration_ms = event.get("durationMs", step.duration_ms)
            step.detail = event.get("detail") or step.detail
            return True

        if kind == "services":
            self.services = list(event.get("services", []))
            return True

        if kind == "result":
            self.url = event.get("url") or ""
            self.output_dir = event.get("outputDir") or ""
            self.edit_user = event.get("editUser") or ""
            self.edit_password = event.get("editPassword") or ""
            return True

        if kind == "error":
            self.error = {
                "step": event.get("step"),
                "message": event.get("message", ""),
                "detail": event.get("detail", ""),
            }
            return True

        return False

    @property
    def current(self):
        """The running step, else the first not yet finished one, else None."""
        for step in self.steps:
            if step.status == RUNNING:
                return step
        for step in self.steps:
            if step.status == PENDING:
                return step
        return None

    @property
    def finished_count(self):
        return sum(1 for s in self.steps if s.status in _FINISHED)

    @property
    def fraction(self):
        """0..1 completion by steps (None when there are no steps to measure)."""
        if not self.steps:
            return None
        return self.finished_count / len(self.steps)

    @property
    def smooth_fraction(self):
        """Like `fraction`, but the running step counts as half done, so the bar
        moves while a long step (building images) is in progress."""
        if not self.steps:
            return None
        running = sum(1 for s in self.steps if s.status == RUNNING)
        return min(1.0, (self.finished_count + 0.5 * running) / len(self.steps))

    @property
    def failed_step(self):
        for step in self.steps:
            if step.status == FAILED:
                return step
        return None

    def services_summary(self):
        """(ready, total, names of the services still pending)."""
        ready = [s for s in self.services if s.get("status") == "ready"]
        waiting = [s.get("name", "?") for s in self.services if s.get("status") == "pending"]
        return len(ready), len(self.services), waiting

    def elapsed(self):
        return time.time() - self.started_at


def format_duration(seconds):
    """"12s" / "3m 04s"."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"
