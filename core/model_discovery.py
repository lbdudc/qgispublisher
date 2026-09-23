"""Discover QGIS geoprocessing models the same way layers are discovered from the
project, instead of requiring the user to export every model to a folder by hand.

QGIS keeps models in two Processing providers:

- ``project`` (id ``"project"``) — models saved *inside* the current project
  (``<projectModels>`` in the .qgz), loaded from the project's XML, not from a file.
- ``model`` (id ``"model"``) — models saved as ``.model3`` files in the user's profile
  models folder(s) (``Processing > Options > Models``), loaded via
  ``QgsProcessingModelAlgorithm.fromFile`` with ``setSourceFilePath()`` recorded.

On top of those, the plugin keeps its existing "extra folder" picker as a third,
explicit source, for models that live outside both of the above (e.g. shared on a
network drive).
"""

import os
import shutil

from qgis.core import QgsApplication, QgsProcessingModelAlgorithm

SOURCE_PROJECT = "Project"
SOURCE_PROFILE = "Profile"
SOURCE_FOLDER = "Folder"


class ModelEntry:
    """A geoprocessing model available to include in the generated application."""

    def __init__(self, entry_id, display_name, group, source, source_file_path="", algorithm=None):
        self.id = entry_id
        self.display_name = display_name
        self.group = group
        self.source = source
        self.source_file_path = source_file_path
        self.algorithm = algorithm

    def parameter_summary(self):
        """Short human-readable summary of the model's inputs, for a tooltip."""
        if self.algorithm is None:
            return ""
        try:
            params = self.algorithm.parameterDefinitions()
        except Exception:
            return "Parameters unavailable (could not read this model's definition)"
        if not params:
            return "No parameters"
        names = [p.description() or p.name() for p in params]
        return "Parameters: " + ", ".join(names)


def _provider_models(provider_id, source_label):
    registry = QgsApplication.processingRegistry()
    provider = registry.providerById(provider_id)
    if provider is None:
        return []

    entries = []
    for alg in provider.algorithms():
        if not isinstance(alg, QgsProcessingModelAlgorithm):
            continue
        try:
            source_file_path = alg.sourceFilePath()
        except Exception:
            source_file_path = ""
        entries.append(
            ModelEntry(
                entry_id=f"{provider_id}:{alg.name()}",
                display_name=alg.displayName() or alg.name(),
                group=alg.group(),
                source=source_label,
                source_file_path=source_file_path or "",
                algorithm=alg,
            )
        )
    return entries


def discover_project_models():
    """Models embedded in the currently open QGIS project."""
    return _provider_models("project", SOURCE_PROJECT)


def discover_profile_models():
    """Models saved in the user's Processing models folder(s)."""
    return _provider_models("model", SOURCE_PROFILE)


def discover_folder_models(folder):
    """Models from an arbitrary folder the user picked, filtered to .model3 files.

    Kept as a fallback source for models that live outside the project and the
    profile models folder (e.g. shared on a network drive).
    """
    entries = []
    if not folder or not os.path.isdir(folder):
        return entries

    for name in sorted(os.listdir(folder)):
        if not name.endswith(".model3"):
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        display_name = name[: -len(".model3")]
        entries.append(
            ModelEntry(
                entry_id=f"folder:{path}",
                display_name=display_name,
                group="",
                source=SOURCE_FOLDER,
                source_file_path=path,
            )
        )
    return entries


def discover_all_models(extra_folder=None):
    """Project models + profile models + (optionally) an extra folder's models,
    deduplicated by algorithm name so the same model saved in more than one place
    (e.g. exported to the profile folder *and* embedded in the project) only shows
    once, preferring the project copy.
    """
    seen_names = set()
    result = []

    for entry in discover_project_models():
        seen_names.add(entry.display_name)
        result.append(entry)

    for entry in discover_profile_models():
        if entry.display_name in seen_names:
            continue
        seen_names.add(entry.display_name)
        result.append(entry)

    if extra_folder:
        for entry in discover_folder_models(extra_folder):
            if entry.display_name in seen_names:
                continue
            seen_names.add(entry.display_name)
            result.append(entry)

    return result


def stage_model(entry, dest_dir):
    """Copy/serialize a ModelEntry's .model3 definition into dest_dir.

    Returns the destination path, or None if staging failed.
    """
    os.makedirs(dest_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in entry.display_name)
    dest_path = os.path.join(dest_dir, safe_name + ".model3")

    if entry.source_file_path and os.path.isfile(entry.source_file_path):
        shutil.copy2(entry.source_file_path, dest_path)
        return dest_path

    if entry.algorithm is not None:
        # Project-embedded models have no backing file — serialize the in-memory
        # algorithm definition to a standalone .model3.
        try:
            if entry.algorithm.toFile(dest_path):
                return dest_path
        except Exception:
            return None

    return None
