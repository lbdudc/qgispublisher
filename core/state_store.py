"""Persistence for the plugin: per-project selections saved in the .qgz, and a
profile-scoped deployment history.

Per-project state uses ``QgsProject.writeEntry``/``readEntry``, the idiomatic QGIS
mechanism for plugin state that should travel with the project and survive a QGIS
restart. Nothing here stores credentials — deploy secrets (AWS keys, SSH usernames/key
paths) are intentionally excluded from both the project entries and the deploy
history; only non-secret deploy fields are ever persisted.
"""

import datetime
import json
import os

SCOPE = "GISPublisher"

# Deploy config fields considered safe to persist/restore: excludes any credential or
# host-identifying secret (AWS access/secret keys, SSH username, SSH key paths).
_RESTORABLE_DEPLOY_FIELDS = {
    "local": ["host"],
    "ssh": ["host", "port", "remote_repo_path"],
    "aws": [
        "region",
        "ami_id",
        "instance_type",
        "instance_name",
        "security_group",
        "key_name",
        "remote_path",
    ],
}

HISTORY_MAX_ENTRIES = 20
HISTORY_LOG_LINES = 50


# ----------------------------------------------------------------------
# Per-project selection (stored in the .qgz)
# ----------------------------------------------------------------------

def save_project_selection(project, selection):
    """Persist the given selection dict into the project's custom properties.

    `selection` keys (all optional): layer_ids (list[str]), model_ids (list[str]),
    chart_folder (str), chart_files (list[str] or None), model_folder (str),
    output_dir (str), action ("generate"/"deploy"), deploy_type (str).
    """
    project.writeEntry(SCOPE, "layers", list(selection.get("layer_ids") or []))
    project.writeEntry(SCOPE, "models", list(selection.get("model_ids") or []))
    project.writeEntry(SCOPE, "chart_folder", selection.get("chart_folder") or "")
    chart_files = selection.get("chart_files")
    # None means "include everything in the folder" — store a sentinel so we can
    # distinguish that from an explicit empty selection on restore.
    if chart_files is None:
        project.writeEntry(SCOPE, "chart_files_all", True)
        project.writeEntry(SCOPE, "chart_files", [])
    else:
        project.writeEntry(SCOPE, "chart_files_all", False)
        project.writeEntry(SCOPE, "chart_files", list(chart_files))
    project.writeEntry(SCOPE, "model_folder", selection.get("model_folder") or "")
    project.writeEntry(SCOPE, "output_dir", selection.get("output_dir") or "")
    project.writeEntry(SCOPE, "action", selection.get("action") or "generate")
    project.writeEntry(SCOPE, "deploy_type", selection.get("deploy_type") or "local")


def load_project_selection(project):
    """Read back the selection saved by save_project_selection.

    Missing entries return sensible defaults (empty lists/strings); callers should
    treat an entirely-empty result as "nothing saved yet" and keep their own default
    behaviour (e.g. select every layer).
    """
    layer_ids, _ = project.readListEntry(SCOPE, "layers", [])
    model_ids, _ = project.readListEntry(SCOPE, "models", [])
    chart_folder, _ = project.readEntry(SCOPE, "chart_folder", "")
    chart_files_all, _ = project.readBoolEntry(SCOPE, "chart_files_all", True)
    chart_files, _ = project.readListEntry(SCOPE, "chart_files", [])
    model_folder, _ = project.readEntry(SCOPE, "model_folder", "")
    output_dir, _ = project.readEntry(SCOPE, "output_dir", "")
    action, _ = project.readEntry(SCOPE, "action", "generate")
    deploy_type, _ = project.readEntry(SCOPE, "deploy_type", "local")

    return {
        "layer_ids": list(layer_ids),
        "model_ids": list(model_ids),
        "chart_folder": chart_folder,
        "chart_files": None if chart_files_all else list(chart_files),
        "model_folder": model_folder,
        "output_dir": output_dir,
        "action": action,
        "deploy_type": deploy_type,
    }


def has_saved_selection(project):
    """Whether anything was ever saved for this project (vs. a brand new project,
    where the caller should fall back to "everything selected")."""
    layer_ids, ok = project.readListEntry(SCOPE, "layers", [])
    return ok


# ----------------------------------------------------------------------
# Deployment history (profile-scoped JSON, no secrets)
# ----------------------------------------------------------------------

def _history_path():
    from qgis.core import QgsApplication

    settings_dir = QgsApplication.qgisSettingsDirPath()
    plugin_dir = os.path.join(settings_dir, "GISPublisher")
    os.makedirs(plugin_dir, exist_ok=True)
    return os.path.join(plugin_dir, "deploy_history.json")


def load_deploy_history():
    path = _history_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return []


def _save_deploy_history(records):
    path = _history_path()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp_path, path)


def append_deploy_record(
    project_title,
    deploy_type,
    host,
    layer_count,
    chart_count,
    model_count,
    exit_code,
    duration_seconds,
    log_lines,
    deploy_fields=None,
):
    """Record a finished deploy run. `deploy_fields` should be the raw fields dict
    collected from the deploy form; only the non-secret subset for `deploy_type` is
    kept (see `_RESTORABLE_DEPLOY_FIELDS`) — credentials are never written to disk.
    """
    restorable = {}
    if deploy_fields:
        for key in _RESTORABLE_DEPLOY_FIELDS.get(deploy_type, []):
            if key in deploy_fields:
                restorable[key] = deploy_fields[key]

    record = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "project_title": project_title or "",
        "deploy_type": deploy_type,
        "host": host or "",
        "layer_count": layer_count,
        "chart_count": chart_count,
        "model_count": model_count,
        "exit_code": exit_code,
        "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        "log_tail": list(log_lines)[-HISTORY_LOG_LINES:] if log_lines else [],
        "restorable_fields": restorable,
    }

    records = load_deploy_history()
    records.append(record)
    records = records[-HISTORY_MAX_ENTRIES:]
    _save_deploy_history(records)
    return record


def clear_deploy_history():
    _save_deploy_history([])
