"""Plan and perform staging every layer the plugin can publish: vector layers as
shapefiles regardless of original source format, local rasters as GeoTIFF, and WMS
layers scoped to the sublayer actually picked.

Split into a pure planning half (``LayerDescriptor``/``plan_exports`` for vectors,
``RasterDescriptor``/``classify_raster`` for rasters) with no QGIS import, and a
QGIS-touching half (``describe_layer``/``export_layer``,
``describe_raster``/``export_raster``) that is a thin adapter over it. Keeping the
decisions in the pure half means they're covered by the QGIS-free suite in
tests/test_layer_export.py — see tests/README or tests/test_naming.py for the same
pattern.

Why shapefile for every source, not just the ones that already are one: the
generator (``@lbdudc/gis-publisher``) only reads shapefile sidecars, and it loads
everything into its own database regardless of the source format, so teaching it
GeoPackage/PostGIS input would be generator-side cost for no user-visible gain.
Exporting through ``QgsVectorFileWriter`` instead means every source QGIS can read
becomes publishable, SLD styling starts working for all of them, and CRS is fixed by
construction (the writer reprojects) rather than merely warned about.
"""

import os
import shutil
import urllib.parse
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
WARN_RESERVED_ENTITY_NAME = "RESERVED_ENTITY_NAME"
WARN_UNSTYLABLE_RENDERER = "UNSTYLABLE_RENDERER"
WARN_DEGRADED_RENDERER = "DEGRADED_RENDERER"

# The plugin's only symbology path is QgsVectorLayer.saveSldStyle()
# (gispublisher_runner._export_sld). Verified empirically against real QGIS
# (headless PyQGIS 3.44, one memory layer per renderer type, actually calling
# saveSldStyle() and reading its (message, ok) result — not just QGIS docs),
# renderer .type() strings split into two groups:
#
# - RENDERER_TYPES_UNSTYLABLE: saveSldStyle() returns ok=False with a
#   "<type> renderer cannot be converted to SLD" message. _export_sld already
#   handles this — no SLD is written and GeoServer falls back to its own
#   generic default style — but the failure only ever surfaces in the run
#   log / History after a full run, not before committing to one.
# - RENDERER_TYPES_DEGRADED: saveSldStyle() returns ok=True ("Created
#   default style file as ...") but the SLD it writes is a generic
#   single-symbol fallback, not the layer's actual point-displacement/
#   cluster look — today this is reported as a plain, unqualified style
#   export success, no warning anywhere at all.
#
# singleSymbol/categorizedSymbol/graduatedSymbol/RuleRenderer all export
# faithfully (also verified) and are intentionally absent from both sets.
RENDERER_TYPES_UNSTYLABLE = frozenset({
    "heatmapRenderer", "25dRenderer", "invertedPolygonRenderer", "nullSymbol",
})
RENDERER_TYPES_DEGRADED = frozenset({"pointDisplacement", "pointCluster"})


@dataclass(frozen=True)
class LayerDescriptor:
    """A plain, QGIS-free snapshot of the parts of a vector layer that affect how
    it's staged. Everything in ``plan_exports`` operates on this, not on a live
    ``QgsVectorLayer`` — build one with ``describe_layer``.

    ``opacity``/``scale_visibility``/``min_scale``/``max_scale``/``field_aliases``
    don't affect staging or ``plan_exports`` at all — they exist so
    ``core.project_manifest.build_layer_entry`` has a single place to read a
    layer's display metadata from, shared with ``RasterDescriptor`` (both
    dataclasses carry the same names, so a manifest builder can treat either
    kind of descriptor identically without an isinstance check).
    """

    layer_id: str
    name: str
    source: str
    crs_authid: str
    feature_count: int
    field_names: tuple
    has_geometry: bool = True
    opacity: float = 1.0
    scale_visibility: bool = False
    min_scale: float = 0.0
    max_scale: float = 0.0
    field_aliases: dict = field(default_factory=dict)
    renderer_type: str = ""


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


def plan_exports(descriptors, target_crs_authid=DEFAULT_TARGET_CRS, basename_by_id=None):
    """Decide, for every layer in `descriptors`, the basename it will be staged
    under and everything else `export_layer` needs — pure computation, no filesystem
    or QGIS access, so the whole decision (including basename collisions) is
    deterministic and testable.

    `descriptors` order matters: pass layers in the same order they'll be exported so
    `naming.assign_staged_basenames` resolves collisions the same way every time (and
    the same way the main dialog's chart validation predicts, when it's given the
    same layers in the same order).

    `basename_by_id`, when given, is used as-is instead of computing basenames from
    `descriptors` alone. Pass this when other layers outside `descriptors` (e.g.
    local rasters staged as GeoTIFF) share the same staged-basename namespace, so a
    raster and a vector layer that would otherwise collide are still deduplicated
    against each other — see naming.assign_staged_basenames.
    """
    if basename_by_id is None:
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
        # gispublisher's createEntityScheme emits `CREATE ENTITY
        # <naming.entity_name(staged_basename)>` with no suffix at all
        # (unlike layer/style identifiers, which always get a "Layer"/
        # "Style" suffix) — so a layer that stages as e.g. "point" or
        # "polygon" collides with the DSL grammar's own TYPE keyword and
        # fails deep inside ANTLR. Checked against the *staged* basename,
        # since that -- not the QGIS layer's display name -- is exactly
        # what becomes the entity identifier.
        if naming.collides_with_dsl_keyword(basename_by_id[d.layer_id]):
            warnings.append(WARN_RESERVED_ENTITY_NAME)
        if d.renderer_type in RENDERER_TYPES_UNSTYLABLE:
            warnings.append(WARN_UNSTYLABLE_RENDERER)
        elif d.renderer_type in RENDERER_TYPES_DEGRADED:
            warnings.append(WARN_DEGRADED_RENDERER)

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
# Raster classification (pure)
# ----------------------------------------------------------------------
#
# QGIS gives every raster layer a "provider type" string, and for the providers this
# module cares about, a `&`-delimited `key=value` source URI with percent-encoded
# values — the exact format QgsDataSourceUri itself produces. Parsing that format
# with plain string operations (rather than importing QgsDataSourceUri) keeps this
# section QGIS-free and testable, at no accuracy cost: it's the same key/value
# vocabulary either way, and this module only ever reads a fixed, known set of keys.

RASTER_PROVIDER_GDAL = "gdal"
RASTER_PROVIDER_WMS = "wms"

RASTER_KIND_LOCAL = "local"  # a real file on disk -> stage as GeoTIFF
RASTER_KIND_WMS = "wms"  # a WMS layer -> add to urls.wms (+ urls.wms.json scoping)
RASTER_KIND_REJECTED = "rejected"  # can't be published; .message explains why


@dataclass(frozen=True)
class RasterDescriptor:
    """A plain, QGIS-free snapshot of a raster layer's identity, for
    ``classify_raster``. Build one with ``describe_raster``.

    The display-metadata fields mirror ``LayerDescriptor``'s (see its
    docstring) so ``core.project_manifest.build_layer_entry`` can read either
    kind of descriptor the same way; ``field_aliases`` has no raster
    equivalent (rasters have no attribute fields), so it's simply absent here.
    """

    layer_id: str
    name: str
    source: str
    provider_type: str
    opacity: float = 1.0
    scale_visibility: bool = False
    min_scale: float = 0.0
    max_scale: float = 0.0


@dataclass
class RasterPlan:
    """The decision for one raster layer: how (or whether) it can be published."""

    layer_id: str
    kind: str
    message: str = ""
    # Only set when kind == RASTER_KIND_WMS: {url, layers, styles, crs, format}, each
    # a str except layers/styles which are lists (possibly empty).
    wms_request: dict = None


def _parse_raster_uri_params(source):
    """``{key: value}`` from a QGIS raster provider URI (see the section comment
    above) — case-sensitive keys as QGIS emits them, values percent-decoded.
    """
    params = {}
    for part in (source or "").split("&"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        params[key] = urllib.parse.unquote(value)
    return params


def _first_param(params, *keys):
    for key in keys:
        value = params.get(key)
        if value:
            return value
    return ""


def classify_raster(descriptor):
    """Decide how `descriptor` should be published — as a local GeoTIFF, a scoped
    WMS request, or rejected with a reason. Never drops a layer silently: every
    return value has a `kind`, and REJECTED always carries a human-readable
    `message` explaining why, for the caller to surface rather than swallow.
    """
    provider = (descriptor.provider_type or "").lower()

    if provider == RASTER_PROVIDER_GDAL:
        return RasterPlan(layer_id=descriptor.layer_id, kind=RASTER_KIND_LOCAL)

    if provider == RASTER_PROVIDER_WMS:
        params = _parse_raster_uri_params(descriptor.source)

        # QGIS represents XYZ tile layers as the "wms" provider with a "type=xyz"
        # URI parameter — there is no separate "xyz" providerType to check instead.
        # The generator has no tile-layer input format at all (its only tile layer
        # is a hardcoded OSM base), so this must be rejected, not mis-published as
        # if it were a WMS service.
        if _first_param(params, "type").lower() == "xyz":
            return RasterPlan(
                layer_id=descriptor.layer_id,
                kind=RASTER_KIND_REJECTED,
                message="XYZ tile layers aren't supported by the generator.",
            )

        url = _first_param(params, "url", "URL")
        if not url:
            return RasterPlan(
                layer_id=descriptor.layer_id,
                kind=RASTER_KIND_REJECTED,
                message="WMS layer has no service URL and can't be published.",
            )

        layers_param = _first_param(params, "layers", "LAYERS")
        styles_param = _first_param(params, "styles", "STYLES")
        request = {
            "url": url,
            "layers": [v for v in layers_param.split(",") if v],
            "styles": [v for v in styles_param.split(",") if v],
            "crs": _first_param(params, "crs", "CRS", "srs", "SRS"),
            "format": _first_param(params, "format", "FORMAT"),
        }

        if not request["layers"]:
            return RasterPlan(
                layer_id=descriptor.layer_id,
                kind=RASTER_KIND_WMS,
                message=(
                    "No specific WMS sublayer was found for this layer — the "
                    "entire remote service may be published instead of just it."
                ),
                wms_request=request,
            )
        return RasterPlan(layer_id=descriptor.layer_id, kind=RASTER_KIND_WMS, wms_request=request)

    if provider.startswith("arcgis"):
        return RasterPlan(
            layer_id=descriptor.layer_id,
            kind=RASTER_KIND_REJECTED,
            message="ArcGIS REST layers aren't supported by the generator.",
        )

    return RasterPlan(
        layer_id=descriptor.layer_id,
        kind=RASTER_KIND_REJECTED,
        message=f'Raster provider "{descriptor.provider_type}" isn\'t supported by the generator.',
    )


# ----------------------------------------------------------------------
# QGIS-touching adapters — everything above this line is pure.
# ----------------------------------------------------------------------

def _layer_opacity(layer):
    """`layer.opacity()` (the unified QgsMapLayer API, QGIS 3.18+) with a safe
    fallback for anything older/unexpected — an opacity the plugin can't read
    should degrade to "fully opaque" (1.0), not break the export."""
    try:
        return float(layer.opacity())
    except Exception:  # nosec B110 - defensive; opacity is display metadata only
        return 1.0


def _field_aliases(layer):
    """``{field_name: alias}`` for fields that actually have a QGIS-configured
    alias distinct from their own name — a field left at its default (no
    alias set, or an alias identical to the name) is deliberately left out.
    """
    return {
        f.name(): f.alias()
        for f in layer.fields()
        if f.alias() and f.alias() != f.name()
    }


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
        opacity=_layer_opacity(layer),
        scale_visibility=bool(layer.hasScaleBasedVisibility()),
        min_scale=float(layer.minimumScale()),
        max_scale=float(layer.maximumScale()),
        field_aliases=_field_aliases(layer),
        renderer_type=(layer.renderer().type() if layer.renderer() else ""),
    )


def describe_raster(layer):
    """Build a `RasterDescriptor` from a live `QgsRasterLayer`."""
    return RasterDescriptor(
        layer_id=layer.id(),
        name=layer.name(),
        source=layer.source() or "",
        provider_type=layer.providerType() or "",
        opacity=_layer_opacity(layer),
        scale_visibility=bool(layer.hasScaleBasedVisibility()),
        min_scale=float(layer.minimumScale()),
        max_scale=float(layer.maximumScale()),
    )


def export_raster(layer, staged_basename, dest_dir):
    """Stage `layer` — already classified as RASTER_KIND_LOCAL — into `dest_dir` as
    `<staged_basename>.tif`. Never raises; a failed export is reported to the caller,
    matching `export_layer`'s contract, so one bad raster doesn't abort the rest.

    The staged extension must be exactly ".tif": the reader's TIFF_EXT and the CLI's
    own output-folder scan both match only that literal suffix, not ".tiff".
    """
    dest_path = os.path.join(dest_dir, staged_basename + ".tif")
    source_path = (layer.source() or "").split("|")[0]

    if os.path.splitext(source_path)[1].lower() in (".tif", ".tiff") and os.path.isfile(source_path):
        # A straight copy preserves every band/nodata/CRS/overview detail exactly —
        # cheaper and safer than a GDAL re-encode for a format GDAL already reads
        # natively as GeoTIFF.
        try:
            shutil.copyfile(source_path, dest_path)
        except OSError as e:
            return False, str(e)
        return True, ""

    from qgis.core import QgsRasterFileWriter, QgsRasterPipe

    provider = layer.dataProvider()
    pipe = QgsRasterPipe()
    if not pipe.set(provider.clone()):
        return False, "could not build a raster pipe for export"

    writer = QgsRasterFileWriter(dest_path)
    writer.setOutputFormat("GTiff")
    error = writer.writeRaster(pipe, provider.xSize(), provider.ySize(), provider.extent(), provider.crs())
    if error != QgsRasterFileWriter.WriterError.NoError:
        return False, f"raster export failed (code {error})"
    return True, ""


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
