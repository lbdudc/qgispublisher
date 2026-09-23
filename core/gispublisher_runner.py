import dataclasses, json, os, re, tempfile, pathlib, shutil, time
from qgis.PyQt.QtCore import QProcess, QUrl
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsMapLayer, QgsProject
from ..core.dependencies_checker import check_node_gispublisher
from ..core import layer_export, model_discovery, naming, project_manifest, shapefile_io

# Staging dirs created under the OS temp dir per run; never cleaned up automatically
# by the OS, so the plugin sweeps stale ones on its own (see cleanup_old_temp_dirs).
_TEMP_PREFIX = "qgis_gispublisher_"
_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60

_HOST_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def cleanup_old_temp_dirs():
    """Remove qgis_gispublisher_* staging directories older than a day.

    Called opportunistically (e.g. when the main dialog opens) since nothing else
    removes these after a run finishes.
    """
    base = tempfile.gettempdir()
    now = time.time()
    try:
        entries = os.listdir(base)
    except OSError:
        return

    for name in entries:
        if not name.startswith(_TEMP_PREFIX):
            continue
        path = os.path.join(base, name)
        try:
            if not os.path.isdir(path):
                continue
            age = now - os.path.getmtime(path)
            if age > _TEMP_MAX_AGE_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _export_sld(layer, dest_path):
    """Write layer's QGIS symbology as an SLD next to its staged shapefile.

    Returns (ok, message). Any failure is non-fatal to the caller — the generator
    falls back to a random-colour style when no SLD is present, matching today's
    behaviour, so a failed export should be reported but never abort the run.
    """
    try:
        result = layer.saveSldStyle(dest_path)
    except Exception as e:  # pragma: no cover - defensive, binding-version dependent
        return False, str(e)

    # QGIS/SIP has returned this call's Out-parameters in slightly different shapes
    # across versions (a bare bool, or a (message, bool) tuple) — handle both.
    ok = None
    message = ""
    if isinstance(result, tuple):
        for part in result:
            if isinstance(part, bool):
                ok = part
            elif isinstance(part, str):
                message = part
    elif isinstance(result, bool):
        ok = result

    wrote_file = os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0
    if ok is None:
        ok = wrote_file

    if ok and wrote_file:
        return True, ""
    return False, message or "style export failed"


class GISPublisherRunner:

    def __init__(self, layers, output_dir, progress_label, progress_bar, output_text, parent=None, finished_callback=None, chart_folder=None, chart_items=None, model_entries=None, debug=False, target_crs=layer_export.DEFAULT_TARGET_CRS):
        self.layers = layers
        self.output_dir = output_dir
        self.target_crs = target_crs
        self.progress_label = progress_label
        self.progress_bar = progress_bar
        self.output_text = output_text
        self.parent = parent
        self.finished_callback = finished_callback
        self.chart_folder = chart_folder
        # None means "include everything in the folder"; a list restricts to those names.
        self.chart_items = chart_items
        # List of model_discovery.ModelEntry already filtered to the checked ones.
        self.model_entries = model_entries or []
        self.temp_dir = tempfile.mkdtemp(prefix=_TEMP_PREFIX)
        # Chart/model subdirectories are created lazily, only once something is
        # actually staged into them — an empty `models/` folder makes the CLI's
        # own file walk (which treats every subfolder but `output` as a data
        # source) fail once it finds nothing to process there.
        self.charts_temp_dir = os.path.join(self.temp_dir, "charts")
        self.models_temp_dir = os.path.join(self.temp_dir, "models")
        self.process = None
        self.debug = debug
        self.cancelled = False
        self.sld_results = []  # list of (layer_name, ok, message)
        self.export_results = []  # list of (layer_name, ok, message)
        self.manifest_layer_entries = []  # list of project_manifest.build_layer_entry() dicts
        self.group_dir_by_name = {}  # {original QGIS group name: staged dirname}, set by copy_layers_directly
        self.log_lines = []
        self._start_time = None
        self.resulting_host = ""

    def _dest_dir_for(self, layer, tree_info, group_dir_by_name):
        """Where `layer`'s staged file(s) belong: a group subdirectory (created
        on first use) if it's inside a QGIS group, else self.temp_dir directly.
        """
        group = tree_info.get(layer.id(), {}).get("group")
        if not group:
            return self.temp_dir
        dest_dir = os.path.join(self.temp_dir, group_dir_by_name[group])
        os.makedirs(dest_dir, exist_ok=True)
        return dest_dir

    def copy_layers_directly(self):
        # Layer-tree position/visibility/group, keyed by QGIS layer id — a
        # property of the tree, not of the layer itself, so it's collected
        # once up front rather than re-derived per layer below. Never raises:
        # a manifest is enrichment, not a requirement (see
        # _write_project_manifest), and an empty dict here just means every
        # manifest_layer_entries entry below falls back to "unknown".
        try:
            tree_info = project_manifest.describe_layer_tree(QgsProject.instance().layerTreeRoot())
        except Exception:
            tree_info = {}

        # One staged subdirectory per top-level-or-nested QGIS group (its
        # immediate parent group's name — see describe_layer_tree), so
        # gispublisher's own directory scan (every staged subdirectory except
        # "output" becomes its own CREATE SORTABLE MAP, see main.js's
        # getDirectories) turns each group into its own map for free, with no
        # CLI/DSL change. Group names are collected here, not from self.layers
        # directly, so a group with every one of its layers unselected still
        # gets a stable dirname — irrelevant in practice (nothing would be
        # staged into it) but keeps this deterministic regardless of
        # selection order. An ungrouped layer (tree_info has no "group", or
        # the layer is missing from tree_info entirely) stays directly in
        # self.temp_dir, exactly as before this existed.
        group_names = []
        for layer in self.layers:
            group = tree_info.get(layer.id(), {}).get("group")
            if group and group not in group_names:
                group_names.append(group)
        # Stashed on self, not just a local, so _write_project_manifest (called
        # separately, after this method returns) can write the dirname ->
        # original-group-name reverse lookup into the manifest — see
        # project_manifest.build_manifest's group_dir_by_name param.
        self.group_dir_by_name = naming.assign_group_dirnames(group_names)
        group_dir_by_name = self.group_dir_by_name

        vector_layers = []
        vector_descriptor_by_id = {}
        local_raster_layers = []
        raster_descriptor_by_id = {}
        wms_requests = []

        for layer in self.layers:
            if layer.type() == QgsMapLayer.LayerType.RasterLayer:
                descriptor = layer_export.describe_raster(layer)
                plan = layer_export.classify_raster(descriptor)
                if plan.kind == layer_export.RASTER_KIND_LOCAL:
                    local_raster_layers.append(layer)
                    raster_descriptor_by_id[layer.id()] = descriptor
                elif plan.kind == layer_export.RASTER_KIND_WMS:
                    wms_requests.append(plan.wms_request)
                    if plan.message:
                        self.log_lines.append(f"[WARN] {layer.name()}: {plan.message}")
                    self.export_results.append((layer.name(), True, ""))
                else:  # RASTER_KIND_REJECTED — every layer gets an export_results
                    # entry, including this one, so a skipped layer is never silently
                    # absent from the run's outcome.
                    self.export_results.append((layer.name(), False, plan.message))
                continue
            if layer.type() == QgsMapLayer.LayerType.VectorLayer:
                vector_layers.append(layer)
                vector_descriptor_by_id[layer.id()] = layer_export.describe_layer(layer)

        # Vector layers and local rasters share ONE staged-basename namespace,
        # computed in the order layers appear in self.layers, so a raster and a
        # vector that would otherwise collide (e.g. "roads.tif" next to "roads.shp")
        # never overwrite each other in the flat temp dir — see
        # naming.assign_staged_basenames.
        basename_candidates = []
        for layer in self.layers:
            descriptor = vector_descriptor_by_id.get(layer.id()) or raster_descriptor_by_id.get(layer.id())
            if descriptor is not None:
                basename_candidates.append(
                    (descriptor.layer_id, naming.preferred_basename_from_source(descriptor.name, descriptor.source))
                )
        basename_by_id = naming.assign_staged_basenames(basename_candidates)

        # Every vector layer is exported through QgsVectorFileWriter (not just the
        # ones that already are shapefiles) so GeoPackage/PostGIS/memory sources
        # become publishable too, CRS is fixed by construction rather than merely
        # warned about, and the plugin — not layer.source() — picks the staged
        # basename, so two layers that would otherwise collide never overwrite each
        # other in the flat temp dir.
        vector_descriptors = [vector_descriptor_by_id[layer.id()] for layer in vector_layers]
        plans = layer_export.plan_exports(vector_descriptors, self.target_crs, basename_by_id=basename_by_id)
        plan_by_id = {plan.layer_id: plan for plan in plans}

        for layer, descriptor in zip(vector_layers, vector_descriptors):
            plan = plan_by_id[layer.id()]
            dest_dir = self._dest_dir_for(layer, tree_info, group_dir_by_name)
            ok, message = layer_export.export_layer(layer, plan, dest_dir, self.target_crs)
            self.export_results.append((layer.name(), ok, message))
            if not ok:
                continue
            for code in plan.warnings:
                self.log_lines.append(f"[WARN] {layer.name()}: {code}")

            # See project_manifest.remap_field_aliases: an alias for a field
            # that also needed a DBF-safe rename must be re-keyed to match,
            # or gispublisher would look it up under a name that no longer
            # exists in the staged file.
            manifest_descriptor = dataclasses.replace(
                descriptor,
                field_aliases=project_manifest.remap_field_aliases(descriptor.field_aliases, plan.rename_map),
            )
            self.manifest_layer_entries.append(project_manifest.build_layer_entry(
                manifest_descriptor, plan.staged_basename, tree_info.get(layer.id())
            ))

            field_names = list(descriptor.field_names)
            staged_dbf = os.path.join(dest_dir, plan.staged_basename + ".dbf")
            if plan.rename_map and os.path.isfile(staged_dbf):
                shapefile_io.rewrite_dbf_field_names(staged_dbf, field_names, plan.rename_map)

            dest_sld = os.path.join(dest_dir, plan.staged_basename + ".sld")
            sld_ok, sld_message = _export_sld(layer, dest_sld)
            self.sld_results.append((layer.name(), sld_ok, sld_message))
            if sld_ok:
                if plan.sld_rename_map:
                    shapefile_io.rewrite_sld_field_references(dest_sld, plan.sld_rename_map)
                shapefile_io.rewrite_unsupported_marks(dest_sld)

        for layer in local_raster_layers:
            staged_basename = basename_by_id[layer.id()]
            dest_dir = self._dest_dir_for(layer, tree_info, group_dir_by_name)
            ok, message = layer_export.export_raster(layer, staged_basename, dest_dir)
            self.export_results.append((layer.name(), ok, message))
            if ok:
                self.manifest_layer_entries.append(project_manifest.build_layer_entry(
                    raster_descriptor_by_id[layer.id()], staged_basename, tree_info.get(layer.id())
                ))

        if wms_requests:
            # urls.wms keeps its original bare-URL-per-line shape (deduplicated) so a
            # reader that doesn't understand the sidecar still works exactly as
            # before, publishing every layer the service advertises. urls.wms.json
            # is additive: a reader that looks for it can scope each service down to
            # just the sublayer(s) actually picked; see WmsProcessor.js.
            seen_urls = []
            for request in wms_requests:
                if request["url"] not in seen_urls:
                    seen_urls.append(request["url"])

            wms_file = os.path.join(self.temp_dir, "urls.wms")
            with open(wms_file, "w", encoding="utf-8") as f:
                f.write("\n".join(seen_urls))

            sidecar_file = wms_file + ".json"
            with open(sidecar_file, "w", encoding="utf-8") as f:
                json.dump(wms_requests, f)

    def copy_chart_folder(self):
        if self.chart_folder and os.path.exists(self.chart_folder):
            for item in os.listdir(self.chart_folder):
                if self.chart_items is not None and item not in self.chart_items:
                    continue
                src_path = os.path.join(self.chart_folder, item)
                if not (os.path.isfile(src_path) or os.path.isdir(src_path)):
                    continue
                os.makedirs(self.charts_temp_dir, exist_ok=True)
                dst_path = os.path.join(self.charts_temp_dir, item)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)

    def copy_model_folder(self):
        for entry in self.model_entries:
            dest_path = model_discovery.stage_model(entry, self.models_temp_dir)
            if dest_path is None:
                self.log_lines.append(
                    f"[WARN] Could not stage model '{entry.display_name}' ({entry.source})"
                )

    def _write_project_manifest(self):
        """Stage qgis-project.json (see core.project_manifest and
        gispublisher/src/manifest-util.js) into the root of the temp dir,
        alongside the layers copy_layers_directly() just staged.

        Deliberately never lets a manifest problem abort the run — an older
        gispublisher CLI ignores the file entirely (it isn't a recognized
        geographic extension), and a newer one treats a missing/malformed
        manifest as "nothing extra to apply", so the worst case here is
        exactly today's behaviour, not a broken run.
        """
        try:
            project_info = project_manifest.describe_project()
            if not project_info.get("extent"):
                project_info["extent"] = project_manifest.layers_extent_wgs84(self.layers)
            manifest = project_manifest.build_manifest(
                project_info, self.manifest_layer_entries, self.group_dir_by_name
            )
            project_manifest.write_manifest(self.temp_dir, manifest)
        except Exception as e:
            self.log_lines.append(f"[WARN] Could not write QGIS project manifest: {e}")

    def start(self, generate=False, config_path=None):
        gispub_path = check_node_gispublisher()
        args = []

        self.generate = generate
        self._start_time = time.time()
        self.copy_layers_directly()
        self._write_project_manifest()
        self.copy_chart_folder()
        self.copy_model_folder()

        if generate:
            shapefiles_folder = self.temp_dir
            args.append(shapefiles_folder)
            args.append("-g")
            working_dir = self.output_dir
            if config_path:
                # Passing a config here is what makes the App name/Version
                # fields actually reach the CLI on a generate run — without
                # it, gispublisher falls back to its own default config.json
                # ("test"/"2.0.0"). Its own --config resolution is
                # cwd-relative with no absolute-path support, so the config
                # must live in (and cwd must be) the same directory — which
                # build_deploy_config's dest_dir already arranges to be
                # output_dir, so this ends up unchanged in practice.
                config_path = pathlib.Path(config_path)
                args.append("--config")
                args.append(config_path.name)
                working_dir = str(config_path.parent)
        elif config_path:  # deploy
            shapefiles_folder = self.temp_dir
            config_path = pathlib.Path(config_path)

            args.append(shapefiles_folder)
            args.append("--config")
            args.append(config_path.name)
            working_dir = str(config_path.parent)
        else:
            raise ValueError("start() requires either generate=True or a config_path")
        self.run_gispublisher(gispub_path, args, working_dir)

    def run_gispublisher(self, gispub_path, args, working_dir=None):
        self.progress_label.setText("Running GISPublisher...")
        self.progress_label.setVisible(True)
        self.progress_bar.setVisible(True)
        # Real progress isn't reported by the GISPublisher CLI, so show a busy
        # (indeterminate) bar instead of a fake, misleading percentage.
        self.progress_bar.setRange(0, 0)

        if self.output_text:
            self.output_text.clear()
            self.output_text.appendPlainText("> Starting GISPublisher...\n")

        for layer_name, ok, message in self.export_results:
            if not ok:
                self.log_lines.append(f"[EXPORT] {layer_name}: NOT PUBLISHED ({message})")
        for layer_name, ok, message in self.sld_results:
            if ok:
                self.log_lines.append(f"[STYLE] {layer_name}: style exported")
            else:
                suffix = f" ({message})" if message else ""
                self.log_lines.append(f"[STYLE] {layer_name}: style not exported{suffix}")
        if self.output_text:
            for line in self.log_lines:
                self.output_text.appendPlainText(line)

        self.process = QProcess()
        self.process.setProgram(gispub_path)
        self.process.setArguments(args)

        if working_dir:
            self.process.setWorkingDirectory(working_dir)

        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.finished)

        self.process.start()

    def cancel(self):
        """Kill the running GISPublisher process, if any."""
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.cancelled = True
            self.process.kill()

    def _record_output(self, text):
        for line in text.splitlines():
            if line.strip():
                self.log_lines.append(line)
                match = _HOST_URL_RE.search(line)
                if match:
                    self.resulting_host = match.group(0).rstrip(".,;")

    def handle_stdout(self):
        # errors="replace": a non-UTF-8 byte from the CLI (e.g. a Windows console's
        # native codepage) must not raise inside this Qt slot and kill the run.
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text.strip():
            self._record_output(text)
            if self.output_text:
                self.output_text.appendPlainText(text.rstrip())

    def handle_stderr(self):
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if text.strip():
            self._record_output(f"[ERROR] {text}")
            if self.output_text:
                self.output_text.appendPlainText(f"[ERROR] {text.rstrip()}")

    def show_error_popup(self, message=None):
        detail = message or "\n".join(self.log_lines[-15:]) or "Execution failed"

        if self.debug:
            self.progress_label.setText("GISPublisher finished with errors ❌")
            self.output_text.appendPlainText(f"\n> ERROR: {detail}")
            return

        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("GISPublisher Error")
        msg_box.setText("An error occurred during GISPublisher execution.")
        msg_box.setInformativeText(detail)
        msg_box.setDetailedText("\n".join(self.log_lines))
        msg_box.exec()

    def failed_export_layers(self):
        """Layers whose export_results entry recorded a failure — dropped rasters,
        rejected providers, and export errors alike. Checked by finished()/
        show_success_popup() so a run where some layers didn't make it in is never
        reported as a bare, unqualified success.
        """
        return [(name, message) for name, ok, message in self.export_results if not ok]

    def show_success_popup(self):
        failed = self.failed_export_layers()

        if self.debug:
            label = "GISPublisher finished ✅" if not failed else f"GISPublisher finished with {len(failed)} warning(s) ⚠️"
            self.progress_label.setText(label)
            self.output_text.appendPlainText("\n> Process completed successfully.")
            return

        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Icon.Information if not failed else QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("Process completed")

        if self.generate:
            text = "The application was generated successfully."
            open_button = msg_box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        else:
            text = "Deployment completed successfully."
            if self.resulting_host:
                text += f"\n\nThe application is available at:\n{self.resulting_host}"
            open_button = None

        if failed:
            text += f"\n\n{len(failed)} layer(s) were not published:\n" + "\n".join(
                f"- {name}: {message}" for name, message in failed
            )
        msg_box.setText(text)

        msg_box.addButton(QMessageBox.StandardButton.Ok)
        msg_box.exec()

        if self.generate and msg_box.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

    def duration_seconds(self):
        if self._start_time is None:
            return None
        return time.time() - self._start_time

    def finished(self, exitCode, exitStatus):
        self.progress_bar.setRange(0, 100)

        if self.cancelled:
            self.progress_bar.setValue(0)
            self.progress_label.setText("GISPublisher cancelled")
            if self.output_text:
                self.output_text.appendPlainText("\n> Process cancelled by user.")
        elif exitCode == 0:
            failed = self.failed_export_layers()
            self.progress_bar.setValue(100)
            self.progress_bar.setStyleSheet("")
            if failed:
                self.progress_label.setText(f"GISPublisher finished with {len(failed)} warning(s) ⚠️")
            else:
                self.progress_label.setText("GISPublisher finished ✅")
            if self.output_text:
                self.output_text.appendPlainText("\n> Process completed successfully.")
            self.show_success_popup()
        else:
            self.progress_label.setText("GISPublisher failed ❌")
            if self.output_text:
                self.output_text.appendPlainText(f"\n> Process finished with errors (exit code {exitCode}).")
            self.show_error_popup()

        self.exit_code = exitCode

        if self.finished_callback:
            self.finished_callback()
