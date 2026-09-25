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


def build_manifest(project_info, layer_entries, group_dir_by_name=None):
    """Pure: assemble the manifest dict from already-collected plain data.

    ``project_info``: ``{"title": str-or-None, "extent": dict-or-None}``,
    where ``extent`` (when present) is
    ``{"crs": "EPSG:4326", "xmin", "ymin", "xmax", "ymax"}`` (floats).
    ``layer_entries``: iterable of per-layer dicts, normally built with
    ``build_layer_entry`` — each needs at least ``"staged"`` (the join key,
    matching the CLI's own staged basename exactly — see
    ``naming.assign_staged_basenames``) and ``"title"``.
    ``group_dir_by_name``: ``{original_qgis_group_name: staged_dirname}``
    (``naming.assign_group_dirnames``'s own return shape) for any layer staged
    into a group subdirectory — written out inverted, ``{dirname: original
    name}``, since gispublisher only ever sees the staged dirname (it becomes
    a map's DSL identifier — see ``naming.dsl_safe_identifier`` — which is
    filesystem/DSL-safe but not necessarily the pretty original name a QGIS
    group can have, e.g. with spaces or accents) and needs the reverse lookup
    to label that group's map with its real name instead.

    A ``None`` value anywhere is dropped rather than written as JSON ``null``,
    so the manifest only ever describes what's actually known and
    gispublisher's consumer can tell "not set" apart from an explicit falsy
    value (e.g. ``"visible": false`` is real data; a missing ``"visible"`` key
    means the plugin couldn't determine it).
    """
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "project": {k: v for k, v in (project_info or {}).items() if v is not None},
        "layers": [
            {k: v for k, v in entry.items() if v is not None}
            for entry in layer_entries
        ],
    }
    if group_dir_by_name:
        manifest["groups"] = {dirname: name for name, dirname in group_dir_by_name.items()}
    return manifest


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
    field_info = getattr(descriptor, "field_info", None)
    if not field_info:
        # A descriptor that only knows aliases (the pre-field_info shape)
        field_info = {
            name: {"alias": alias}
            for name, alias in (getattr(descriptor, "field_aliases", None) or {}).items()
        }
    fields = [
        {"name": name, **{k: v for k, v in info.items() if v is not None}}
        for name, info in field_info.items()
        if info
    ]
    if fields:
        entry["fields"] = fields
    display_field = getattr(descriptor, "display_field", "")
    if display_field:
        entry["displayField"] = display_field
    temporal = getattr(descriptor, "temporal", None)
    if temporal:
        entry["temporal"] = dict(temporal)
    popup_template = getattr(descriptor, "popup_template", "")
    if popup_template:
        entry["popup"] = {"template": popup_template}
    return entry


def build_bookmark_entries(named_extents):
    """Pure: ``[(name, wgs84_extent_dict_or_None), ...]`` -> the manifest's
    ``project.bookmarks`` list of ``{"name", "xmin", "ymin", "xmax", "ymax"}``.
    A bookmark with no name, or whose extent couldn't be reprojected to
    EPSG:4326, is dropped — the generated app can't fly to it either way.
    """
    entries = []
    for name, extent in named_extents:
        name = (name or "").strip()
        if not name or not extent:
            continue
        entries.append({
            "name": name,
            "xmin": extent["xmin"],
            "ymin": extent["ymin"],
            "xmax": extent["xmax"],
            "ymax": extent["ymax"],
        })
    return entries


def build_crs_info(authid, is_geographic, proj4=None):
    """Pure: the manifest's ``project.crs`` block. ``authid`` is e.g.
    ``"EPSG:25829"`` (empty for a custom CRS with no authority id, in which
    case there is nothing gispublisher could name it by — returns ``None``).
    """
    if not authid:
        return None
    info = {"authid": authid, "isGeographic": bool(is_geographic)}
    if proj4:
        info["proj4"] = proj4
    return info


def extent_in_project_crs(extent_wgs84):
    """``extent_wgs84`` (the manifest's ``project.extent`` dict) transformed into
    the QGIS project's own CRS, as ``{"xmin","ymin","xmax","ymax"}``, or ``None``.
    gispublisher needs it to size a custom Leaflet CRS's resolutions.
    """
    from qgis.core import (
        QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle,
    )

    try:
        project = QgsProject.instance()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        rect = QgsRectangle(
            extent_wgs84["xmin"], extent_wgs84["ymin"], extent_wgs84["xmax"], extent_wgs84["ymax"]
        )
        rect = QgsCoordinateTransform(wgs84, project.crs(), project).transformBoundingBox(rect)
        return {
            "xmin": rect.xMinimum(), "ymin": rect.yMinimum(),
            "xmax": rect.xMaximum(), "ymax": rect.yMaximum(),
        }
    except Exception:
        return None


def remap_field_aliases(field_aliases, rename_map):
    """``field_aliases`` (keyed by the *original* QGIS field name) re-keyed
    through ``rename_map`` (``ExportPlan.rename_map``, original -> DBF-safe
    name) so its keys match what gispublisher's entity-scheme builder reads
    back off the *staged* DBF, not the field's original QGIS name. A field
    absent from ``rename_map`` (the common case — most fields need no DBF-safe
    rename at all) keeps its original name unchanged.
    """
    return remap_field_keys(field_aliases, rename_map)


def remap_field_keys(by_field, rename_map):
    """Any mapping keyed by the *original* QGIS field name (aliases, ``field_info``)
    re-keyed through ``rename_map``, so it matches the staged DBF's field names.
    Values are left as they are.
    """
    if not rename_map:
        return by_field
    return {rename_map.get(name, name): value for name, value in by_field.items()}


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

    return {
        "title": title,
        "extent": extent,
        "crs": _describe_project_crs(project),
        "bookmarks": _describe_bookmarks(project),
    }


def _describe_project_crs(project):
    """``project.crs`` for the manifest, best-effort (``None`` on any failure)."""
    try:
        crs = project.crs()
        if not crs.isValid():
            return None
        try:
            proj4 = crs.toProj()
        except Exception:  # nosec B110 - older QGIS; the proj4 string is optional
            proj4 = None
        return build_crs_info(crs.authid(), crs.isGeographic(), proj4)
    except Exception:
        return None


def _describe_bookmarks(project):
    """The project's own spatial bookmarks as WGS84 extents, best-effort."""
    try:
        named = []
        for bookmark in project.bookmarkManager().bookmarks():
            extent = bookmark.extent()
            named.append((bookmark.name(), _extent_to_wgs84_dict(extent, extent.crs())))
        return build_bookmark_entries(named) or None
    except Exception:
        return None


def _is_service_layer(layer):
    try:
        return layer.providerType() == "wms"
    except Exception:
        return False


def layers_extent_wgs84(layers):
    """Union of ``layers``' extents, reprojected to EPSG:4326 — the fallback
    used when the project has no saved view extent. ``layers`` are live QGIS
    map layers (vector or raster); a layer with an invalid/empty extent, or
    one that fails to reproject, is skipped rather than aborting the whole
    calculation. Returns ``None`` if nothing usable was found.
    """
    from qgis.core import QgsRectangle

    # A tile/WMS basemap (an XYZ OpenStreetMap layer, say) covers the whole world and
    # would make the app open zoomed out on the planet: the data layers decide the
    # view, and the service layers only count when nothing else has an extent.
    layers = list(layers)
    data_layers = [layer for layer in layers if not _is_service_layer(layer)]
    return _union_extent_wgs84(data_layers) or _union_extent_wgs84(layers)


def _union_extent_wgs84(layers):
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


GROUP_PATH_SEPARATOR = " / "


def join_group_path(parent, name):
    """The name of a nested QGIS group: ``"Parent / Child"`` (just ``name`` at the top
    level). The full path, so two subgroups called the same in different groups stay
    apart, and the generated map is titled by where the group is."""
    return f"{parent}{GROUP_PATH_SEPARATOR}{name}" if parent else name


def describe_layer_tree(root):
    """Walk ``root`` (``QgsProject.instance().layerTreeRoot()``) depth-first,
    in the same top-to-bottom order the Layers panel shows, and return
    ``{layer_id: {"order": int, "visible": bool, "group": str-or-None}}``.

    ``order`` is a plain 0-based position counter over every layer in the
    tree (not per-group), matching what "layer order" means to a QGIS user
    scanning the panel top to bottom. ``group`` is the parent
    ``QgsLayerTreeGroup``'s full path (``join_group_path``: ``"Parent / Child"``
    for a nested one), or ``None`` for a layer sitting directly under the root.
    """
    from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer

    info = {}
    counter = {"n": 0}

    def _walk(node, group_name):
        for child in node.children():
            if isinstance(child, QgsLayerTreeGroup):
                _walk(child, join_group_path(group_name, child.name()))
            elif isinstance(child, QgsLayerTreeLayer):
                info[child.layerId()] = {
                    "order": counter["n"],
                    "visible": bool(child.itemVisibilityChecked()),
                    "group": group_name,
                }
                counter["n"] += 1

    _walk(root, None)
    return info
