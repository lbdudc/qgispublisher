"""Plan and perform staging every vector layer as a shapefile, regardless of its
original source format.

Split into a pure planning half (``LayerDescriptor``, ``plan_exports``) with no QGIS
import, and a QGIS-touching half (``describe_layer``, ``export_layer``) that is a
thin adapter over it. Keeping the decisions in the pure half means they're covered by
the QGIS-free suite in tests/test_layer_export.py — see tests/README or
tests/test_naming.py for the same pattern.

Why shapefile for every source, not just the ones that already are one: the
generator (``@lbdudc/gis-publisher``) only reads shapefile sidecars, and it loads
everything into its own database regardless of the source format, so teaching it
GeoPackage/PostGIS input would be generator-side cost for no user-visible gain.
Exporting through ``QgsVectorFileWriter`` instead means every source QGIS can read
becomes publishable, SLD styling starts working for all of them, and CRS is fixed by
construction (the writer reprojects) rather than merely warned about.
"""

import os
from dataclasses import dataclass, field

from . import naming

# ESRI Shapefile format limits an export can hit that a GeoPackage/PostGIS source
# would never have run into.
MAX_DBF_FIELDS = 255
MAX_SHP_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # classic SHP/DBF 2 GB cap

DEFAULT_TARGET_CRS = "EPSG:4326"

WARN_NO_CRS = "NO_CRS"
WARN_MIXED_CRS = "MIXED_CRS"  # reserved for preflight; not emitted by plan_exports itself
WARN_EMPTY_LAYER = "EMPTY_LAYER"
WARN_NO_GEOMETRY = "NO_GEOMETRY"
WARN_TOO_MANY_FIELDS = "TOO_MANY_FIELDS"
WARN_RENAMED_FIELDS = "RENAMED_FIELDS"


@dataclass(frozen=True)
class LayerDescriptor:
    """A plain, QGIS-free snapshot of the parts of a vector layer that affect how
    it's staged. Everything in ``plan_exports`` operates on this, not on a live
    ``QgsVectorLayer`` — build one with ``describe_layer``.
    """

    layer_id: str
    name: str
    source: str
    crs_authid: str
    feature_count: int
    field_names: tuple
    has_geometry: bool = True


@dataclass
class ExportPlan:
    """The decision for one layer: what to name it, whether to reproject it, which
    fields to rename before/after writing, and anything worth warning the user about.
    """

    layer_id: str
    staged_basename: str
    needs_reproject: bool
    rename_map: dict
    sld_rename_map: dict
    warnings: list = field(default_factory=list)


def plan_exports(descriptors, target_crs_authid=DEFAULT_TARGET_CRS):
    """Decide, for every layer in `descriptors`, the basename it will be staged
    under and everything else `export_layer` needs — pure computation, no filesystem
    or QGIS access, so the whole decision (including basename collisions) is
    deterministic and testable.

    `descriptors` order matters: pass layers in the same order they'll be exported so
    `naming.assign_staged_basenames` resolves collisions the same way every time (and
    the same way the main dialog's chart validation predicts, when it's given the
    same layers in the same order).
    """
    candidates = [
        (d.layer_id, naming.preferred_basename_from_source(d.name, d.source))
        for d in descriptors
    ]
    basename_by_id = naming.assign_staged_basenames(candidates)

    plans = []
    for d in descriptors:
        warnings = []
        if not d.crs_authid:
            warnings.append(WARN_NO_CRS)
        if d.feature_count == 0:
            warnings.append(WARN_EMPTY_LAYER)
        if not d.has_geometry:
            warnings.append(WARN_NO_GEOMETRY)
        if len(d.field_names) > MAX_DBF_FIELDS:
            warnings.append(WARN_TOO_MANY_FIELDS)

        rename_map = naming.rename_map_for_fields(list(d.field_names))
        if rename_map:
            warnings.append(WARN_RENAMED_FIELDS)

        # rename_map only covers fields that are DBF-unsafe (see safe_field_name) —
        # a short, already-valid field name like "TOTAL" is deliberately left out so
        # the staged DBF keeps its exact original name. But dsl-util.js's entity
        # schema builder lowercases every field unconditionally when deriving the
        # generated app's JPA/DB column name, regardless of what's in the DBF — so
        # an SLD rewrite needs the full field -> naming.attribute_name() mapping,
        # not just the DBF-unsafe subset, or a style filtering on "TOTAL" ends up
        # referencing an attribute the generated featuretype doesn't have and
        # GeoServer silently falls back to its own generic default style.
        sld_rename_map = {
            name: naming.attribute_name(name)
            for name in d.field_names
            if naming.attribute_name(name) != name
        }

        needs_reproject = bool(d.crs_authid) and d.crs_authid != target_crs_authid

        plans.append(ExportPlan(
            layer_id=d.layer_id,
            staged_basename=basename_by_id[d.layer_id],
            needs_reproject=needs_reproject,
            rename_map=rename_map,
            sld_rename_map=sld_rename_map,
            warnings=warnings,
        ))
    return plans


# ----------------------------------------------------------------------
# QGIS-touching adapters — everything above this line is pure.
# ----------------------------------------------------------------------

def describe_layer(layer):
    """Build a `LayerDescriptor` from a live `QgsVectorLayer`. The only place in this
    module that touches QGIS besides `export_layer`.
    """
    crs = layer.crs()
    return LayerDescriptor(
        layer_id=layer.id(),
        name=layer.name(),
        source=layer.source() or "",
        crs_authid=crs.authid() if crs and crs.isValid() else "",
        feature_count=layer.featureCount(),
        field_names=tuple(f.name() for f in layer.fields()),
        has_geometry=layer.isSpatial(),
    )


def export_layer(layer, plan, dest_dir, target_crs_authid=DEFAULT_TARGET_CRS):
    """Write `layer` to `dest_dir` as a shapefile named `plan.staged_basename`,
    reprojecting to `target_crs_authid` when `plan.needs_reproject`. Returns
    (ok, message); a failed export is reported to the caller, never raised, so one
    bad layer doesn't abort staging the rest.
    """
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsProject,
        QgsVectorFileWriter,
        QgsWkbTypes,
    )

    dest_path = os.path.join(dest_dir, plan.staged_basename + ".shp")
    transform_context = QgsProject.instance().transformContext()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "ESRI Shapefile"
    options.fileEncoding = "UTF-8"
    # SaveVectorOptions has no destCRS property in this API — only `ct`, an actual
    # QgsCoordinateTransform. Setting a nonexistent attribute name here would be a
    # silent no-op (SIP wrapper objects accept arbitrary Python attributes without
    # erroring), so reprojection must go through a real transform.

    if plan.needs_reproject:
        target_crs = QgsCoordinateReferenceSystem(target_crs_authid)
        if target_crs.isValid():
            options.ct = QgsCoordinateTransform(layer.crs(), target_crs, transform_context)

    # The generated app's PostGIS columns are always declared 2D (the platform has
    # nowhere to display elevation), but a source with Z-enabled geometries (e.g. a
    # point layer digitized with elevation, or a shapefile whose shape type is
    # PointZ/PolygonZ regardless of whether any Z value is actually non-zero) writes
    # a 3D shapefile by default. PostGIS then rejects every single feature on import
    # with "Geometry has Z dimension but column does not" — the import step reports
    # HTTP 200 (each bad feature is skipped, not raised) and the layer silently ends
    # up with zero rows, which is indistinguishable from an empty source layer until
    # you check the database. Flattening to 2D at export time, before the generator
    # ever sees the file, avoids that class of silent data loss entirely.
    if QgsWkbTypes.hasZ(layer.wkbType()):
        options.overrideGeometryType = QgsWkbTypes.dropZ(layer.wkbType())

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, dest_path, transform_context, options
    )
    # writeAsVectorFormatV3 returns a (QgsVectorFileWriter.WriterError, str) tuple in
    # every QGIS 3.x that has the V3 API; NoError == 0.
    error_code, message = result[0], (result[1] if len(result) > 1 else "")
    if error_code != QgsVectorFileWriter.WriterError.NoError:
        return False, message or f"export failed (code {error_code})"
    return True, ""
