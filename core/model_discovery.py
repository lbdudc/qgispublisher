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
    # Deferred: keeps this module importable (and discover_all_models's pure
    # dedup logic, ModelEntry, discover_folder_models and stage_model
    # testable) outside a running QGIS — same convention as state_store.py's
    # _history_path().
    from qgis.core import QgsApplication, QgsProcessingModelAlgorithm

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


# ----------------------------------------------------------------------
# Preflight: will this model actually run in the generated app's WPS service?
# ----------------------------------------------------------------------
#
# The generated product runs models in a `3liz/qgis-wps` container against a
# processing project rebuilt from the app's layers (all stored in EPSG:4326).
# Three things a model can do that work fine in QGIS but not there:
#
# 1. call algorithms from a provider that container doesn't have;
# 2. take a vector input none of the layers being published can satisfy;
# 3. hard-code a distance (a buffer of 2000, say) authored for a metric CRS,
#    which then means 2000 *degrees* on the app's geographic data.
#
# `analyze_model` is pure — it works on the plain dict ``toVariant()`` gives
# (shape captured from a real model in tests/test_model_discovery.py) so it
# runs outside QGIS; `model_variant` / `describe_layer_geometries` /
# `algorithm_parameter_type` are the thin QGIS-touching adapters.

# Processing providers present in the generated app's WPS image.
WPS_SUPPORTED_PROVIDERS = ("native", "qgis", "gdal")

# QgsProcessing::SourceType values a vector parameter's `data_types` can hold.
_GEOMETRY_BY_DATA_TYPE = {0: "point", 1: "line", 2: "polygon"}
_STATIC_VALUE_SOURCE = 2  # QgsProcessingModelChildParameterSource::StaticValue


def _required_geometries(data_types):
    """The geometry kinds a vector parameter accepts, or ``None`` for "any"."""
    if not data_types:
        return None
    wanted = set()
    for data_type in data_types:
        if data_type not in _GEOMETRY_BY_DATA_TYPE:
            return None  # -1 any geometry / 5 any vector / -2 any map layer
        wanted.add(_GEOMETRY_BY_DATA_TYPE[data_type])
    return wanted


def analyze_model(variant, param_type_lookup=None, layer_geometries=None,
                  processing_crs_geographic=True):
    """Warnings (list of str) for one model, from its ``toVariant()`` dict.

    ``param_type_lookup(alg_id, param_name)`` -> QGIS parameter type string
    (``"distance"``...) or ``None``; without it the distance check is skipped.
    ``layer_geometries``: set of ``"point"``/``"line"``/``"polygon"`` among the
    vector layers being published, or ``None`` to skip the input-matching check.
    ``processing_crs_geographic``: whether the generated app will run the model
    in a geographic CRS (true unless the project CRS is projected).
    """
    warnings = []
    variant = variant or {}

    for child in (variant.get("children") or {}).values():
        alg_id = child.get("alg_id") or ""
        provider = alg_id.split(":", 1)[0]
        if provider and provider not in WPS_SUPPORTED_PROVIDERS:
            warnings.append(
                f"Uses '{alg_id}': the '{provider}' provider is not available in the "
                "generated app's processing service, so this step will fail there."
            )
            continue

        if not (param_type_lookup and processing_crs_geographic):
            continue
        for name, sources in (child.get("params") or {}).items():
            for source in sources or []:
                if source.get("source") != _STATIC_VALUE_SOURCE:
                    continue
                value = source.get("static_value")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not value:
                    continue
                if param_type_lookup(alg_id, name) == "distance":
                    warnings.append(
                        f"'{alg_id}' has a fixed distance of {value:g} ({name}). The app "
                        "processes geographic (EPSG:4326) data, so that would be read as "
                        f"{value:g} degrees, not metres."
                    )

    if layer_geometries is not None:
        for definition in (variant.get("parameterDefinitions") or {}).values():
            if definition.get("parameter_type") not in ("vector", "source"):
                continue
            label = definition.get("description") or definition.get("name")
            wanted = _required_geometries(definition.get("data_types"))
            if wanted is None:
                if not layer_geometries:
                    warnings.append(f"Input '{label}' needs a vector layer, but none is being published.")
            elif not wanted & layer_geometries:
                warnings.append(
                    f"Input '{label}' needs a {'/'.join(sorted(wanted))} layer, but none of the "
                    "layers being published has that geometry."
                )
    return warnings


def model_variant(entry):
    """The model's ``toVariant()`` dict — from its live algorithm, else loaded
    from its file. ``None`` if neither works (nothing to analyze)."""
    from qgis.core import QgsProcessingModelAlgorithm

    algorithm = entry.algorithm
    if algorithm is None and entry.source_file_path and os.path.isfile(entry.source_file_path):
        algorithm = QgsProcessingModelAlgorithm()
        if not algorithm.fromFile(entry.source_file_path):
            return None
    try:
        return algorithm.toVariant() if algorithm is not None else None
    except Exception:
        return None


def algorithm_parameter_type(alg_id, param_name):
    """QGIS parameter type of ``alg_id``'s ``param_name`` (``"distance"``...)."""
    from qgis.core import QgsApplication

    algorithm = QgsApplication.processingRegistry().algorithmById(alg_id)
    definition = algorithm.parameterDefinition(param_name) if algorithm else None
    return definition.type() if definition else None


def describe_layer_geometries(layers):
    """``{"point","line","polygon"}`` among live QGIS vector ``layers``."""
    from qgis.core import QgsWkbTypes

    names = {0: "point", 1: "line", 2: "polygon"}
    found = set()
    for layer in layers:
        try:
            kind = names.get(int(QgsWkbTypes.geometryType(layer.wkbType())))
        except Exception:  # nosec B112 - a layer with no geometry can't satisfy an input anyway
            continue
        if kind:
            found.add(kind)
    return found


def model_warnings(entry, layers=None, project_crs_geographic=True):
    """Preflight warnings for one ``ModelEntry``: ``layers`` are the live QGIS
    layers being published (``None`` skips the input-matching check).
    Never raises — a model we can't read just gets no warnings."""
    try:
        variant = model_variant(entry)
        if not variant:
            return []
        geometries = describe_layer_geometries(
            [l for l in layers if hasattr(l, "wkbType")]
        ) if layers is not None else None
        return analyze_model(
            variant,
            param_type_lookup=algorithm_parameter_type,
            layer_geometries=geometries,
            processing_crs_geographic=project_crs_geographic,
        )
    except Exception:
        return []
