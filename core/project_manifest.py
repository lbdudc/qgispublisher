"""Builds ``qgis-project.json``, the sidecar manifest staged alongside the
layers ``gispublisher_runner`` exports — QGIS-side metadata (project
title/extent, and per-layer display name/visibility/order/opacity/scale
range/field aliases) that gispublisher's file-extension scan has no way to
discover on its own. See CLAUDE.md's dev-loop section and
``gispublisher/src/manifest-util.js``, which reads this file back.

Split pure/adapter like ``core.layer_export``: ``build_manifest`` and
``build_layer_entry`` take plain data and return JSON-able dicts (covered by
``tests/test_project_manifest.py``); ``describe_project``,
``layers_extent_wgs84`` and ``describe_layer_tree`` are the QGIS-touching
adapters, and ``write_manifest`` is the thin filesystem writer. Nothing here
should ever raise in a way that aborts a run — a manifest is enrichment, not a
requirement, and gispublisher treats a missing one exactly like every release
before this file existed (see ``gispublisher_runner._write_project_manifest``,
which wraps all of this in a single try/except for that reason).
"""

import json
import os

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "qgis-project.json"


def build_manifest(project_info, layer_entries):
    """Pure: assemble the manifest dict from already-collected plain data.

    ``project_info``: ``{"title": str-or-None, "extent": dict-or-None}``,
    where ``extent`` (when present) is
    ``{"crs": "EPSG:4326", "xmin", "ymin", "xmax", "ymax"}`` (floats).
    ``layer_entries``: iterable of per-layer dicts, normally built with
    ``build_layer_entry`` — each needs at least ``"staged"`` (the join key,
    matching the CLI's own staged basename exactly — see
    ``naming.assign_staged_basenames``) and ``"title"``.

    A ``None`` value anywhere is dropped rather than written as JSON ``null``,
    so the manifest only ever describes what's actually known and
    gispublisher's consumer can tell "not set" apart from an explicit falsy
    value (e.g. ``"visible": false`` is real data; a missing ``"visible"`` key
    means the plugin couldn't determine it).
    """
    return {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "project": {k: v for k, v in (project_info or {}).items() if v is not None},
        "layers": [
            {k: v for k, v in entry.items() if v is not None}
            for entry in layer_entries
        ],
    }


def build_layer_entry(descriptor, staged_basename, tree_entry=None):
    """One ``manifest["layers"]`` entry — pure, and works for either a vector
    ``layer_export.LayerDescriptor`` or a (local, GeoTIFF-staged)
    ``layer_export.RasterDescriptor``, since both share every attribute this
    reads (see their docstrings). ``tree_entry``, when given, is one value
    from ``describe_layer_tree``'s result, keyed by this layer's QGIS layer id
    — i.e. ``tree_info.get(layer.id())``.
    """
    tree_entry = tree_entry or {}
    raw = {
        "staged": staged_basename,
        "title": descriptor.name,
        "visible": tree_entry.get("visible"),
        "order": tree_entry.get("order"),
        "group": tree_entry.get("group"),
        "opacity": descriptor.opacity,
        "minScale": descriptor.min_scale if descriptor.scale_visibility else None,
        "maxScale": descriptor.max_scale if descriptor.scale_visibility else None,
    }
    # Dropped here (not left for build_manifest to clean up) so a
    # build_layer_entry result is already a valid, self-contained manifest
    # entry on its own — "not known" (tree_entry missing a key, scale-based
    # visibility off) should never be confused with an explicit falsy value
    # like "visible": false.
    entry = {k: v for k, v in raw.items() if v is not None}
    field_aliases = getattr(descriptor, "field_aliases", None)
    if field_aliases:
        entry["fields"] = [
            {"name": name, "alias": alias} for name, alias in field_aliases.items()
        ]
    return entry


def remap_field_aliases(field_aliases, rename_map):
    """``field_aliases`` (keyed by the *original* QGIS field name) re-keyed
    through ``rename_map`` (``ExportPlan.rename_map``, original -> DBF-safe
    name) so its keys match what gispublisher's entity-scheme builder reads
    back off the *staged* DBF, not the field's original QGIS name. A field
    absent from ``rename_map`` (the common case — most fields need no DBF-safe
    rename at all) keeps its original name unchanged.
    """
    if not rename_map:
        return field_aliases
    return {
        rename_map.get(name, name): alias
        for name, alias in field_aliases.items()
    }


def write_manifest(temp_dir, manifest):
    """Write ``manifest`` as ``qgis-project.json`` into ``temp_dir`` (the
    staged folder root, where gispublisher's ``manifest-util.js`` looks for
    it) — a plain filesystem write, no QGIS access. Returns the path written.
    """
    path = os.path.join(temp_dir, MANIFEST_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return path


# ----------------------------------------------------------------------
# QGIS-touching adapters — everything above this line is pure.
# ----------------------------------------------------------------------

def describe_project():
    """Project-level manifest info: title and extent, both best-effort.

    Title falls back the same way the main dialog's own app-name default does
    (``project.title() or project.baseName()``) — see
    ``dialogs/qgispublisher_dialog.py``'s ``_apply_default_app_identity``.
    Extent comes from the project's saved view extent when one is set (the
    map canvas state QGIS persists into the .qgz); when there isn't one, this
    returns ``extent: None`` and the caller should fall back to unioning the
    extents of the layers actually being published — see
    ``layers_extent_wgs84``.
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    title = project.title() or project.baseName() or None

    extent = None
    try:
        view_extent = project.viewSettings().defaultViewExtent()
        if view_extent and not view_extent.isEmpty():
            extent = _extent_to_wgs84_dict(view_extent, project.crs())
    except Exception:  # nosec B110 - best-effort; caller has a layer-union fallback
        pass

    return {"title": title, "extent": extent}


def layers_extent_wgs84(layers):
    """Union of ``layers``' extents, reprojected to EPSG:4326 — the fallback
    used when the project has no saved view extent. ``layers`` are live QGIS
    map layers (vector or raster); a layer with an invalid/empty extent, or
    one that fails to reproject, is skipped rather than aborting the whole
    calculation. Returns ``None`` if nothing usable was found.
    """
    from qgis.core import QgsRectangle

    combined = QgsRectangle()
    combined.setMinimal()
    any_valid = False

    for layer in layers:
        try:
            extent = layer.extent()
        except Exception:  # nosec B112 - one bad layer shouldn't drop the rest
            continue
        if extent is None or extent.isEmpty():
            continue
        wgs84_dict = _extent_to_wgs84_dict(extent, layer.crs())
        if wgs84_dict is None:
            continue
        combined.combineExtentWith(QgsRectangle(
            wgs84_dict["xmin"], wgs84_dict["ymin"], wgs84_dict["xmax"], wgs84_dict["ymax"]
        ))
        any_valid = True

    if not any_valid or combined.isEmpty():
        return None
    return {
        "crs": "EPSG:4326",
        "xmin": combined.xMinimum(),
        "ymin": combined.yMinimum(),
        "xmax": combined.xMaximum(),
        "ymax": combined.yMaximum(),
    }


def _extent_to_wgs84_dict(extent, source_crs):
    """``extent`` (a ``QgsRectangle`` in ``source_crs``) reprojected to
    EPSG:4326, as the plain ``{"crs","xmin","ymin","xmax","ymax"}`` dict the
    manifest carries. Returns ``None`` if the transform fails (invalid CRS,
    an extent QGIS can't project into WGS84's bounds, etc.) rather than
    raising — extent is enrichment, and mini-lps's own hardcoded fallback
    bbox is always there if this comes back empty.
    """
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

    try:
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if source_crs and source_crs.isValid() and source_crs != wgs84:
            transform = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)
        return {
            "crs": "EPSG:4326",
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        }
    except Exception:
        return None


def describe_layer_tree(root):
    """Walk ``root`` (``QgsProject.instance().layerTreeRoot()``) depth-first,
    in the same top-to-bottom order the Layers panel shows, and return
    ``{layer_id: {"order": int, "visible": bool, "group": str-or-None}}``.

    ``order`` is a plain 0-based position counter over every layer in the
    tree (not per-group), matching what "layer order" means to a QGIS user
    scanning the panel top to bottom. ``group`` is the immediate parent
    ``QgsLayerTreeGroup``'s name, or ``None`` for a layer sitting directly
    under the root (no group) — a full group *path* isn't tracked since
    nothing downstream needs more than the immediate group yet (see
    Workstream 3d in the plan, which stages one subfolder per top-level
    group instead of consuming this field for grouping).
    """
    from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer

    info = {}
    counter = {"n": 0}

    def _walk(node, group_name):
        for child in node.children():
            if isinstance(child, QgsLayerTreeGroup):
                _walk(child, child.name())
            elif isinstance(child, QgsLayerTreeLayer):
                info[child.layerId()] = {
                    "order": counter["n"],
                    "visible": bool(child.itemVisibilityChecked()),
                    "group": group_name,
                }
                counter["n"] += 1

    _walk(root, None)
    return info
