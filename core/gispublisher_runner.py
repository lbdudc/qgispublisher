import os, re, tempfile, pathlib, shutil, time, urllib.parse
from qgis.PyQt.QtCore import QProcess, QUrl
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import QgsMapLayer
from ..core.dependencies_checker import check_node_gispublisher
from ..core import layer_export, model_discovery, shapefile_io

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
        self.log_lines = []
        self._start_time = None
        self.resulting_host = ""

    def copy_layers_directly(self):
        wms_urls = []
        vector_layers = []

        for layer in self.layers:
            if layer.type() == QgsMapLayer.LayerType.RasterLayer:
                source = layer.source()
                # WMS layers include "url=" in their source string
                if "url=" in source.lower():
                    parts = dict(
                        part.split("=", 1)
                        for part in source.split("&")
                        if "=" in part
                    )
                    url = parts.get("url") or parts.get("URL")
                    if url:
                        wms_urls.append(urllib.parse.unquote(url))
                continue
            if layer.type() == QgsMapLayer.LayerType.VectorLayer:
                vector_layers.append(layer)

        # Every vector layer is exported through QgsVectorFileWriter (not just the
        # ones that already are shapefiles) so GeoPackage/PostGIS/memory sources
        # become publishable too, CRS is fixed by construction rather than merely
        # warned about, and the plugin — not layer.source() — picks the staged
        # basename, so two layers that would otherwise collide never overwrite each
        # other in the flat temp dir.
        descriptors = [layer_export.describe_layer(layer) for layer in vector_layers]
        plans = layer_export.plan_exports(descriptors, self.target_crs)
        plan_by_id = {plan.layer_id: plan for plan in plans}

        for layer, descriptor in zip(vector_layers, descriptors):
            plan = plan_by_id[layer.id()]
            ok, message = layer_export.export_layer(layer, plan, self.temp_dir, self.target_crs)
            self.export_results.append((layer.name(), ok, message))
            if not ok:
                continue
            for code in plan.warnings:
                self.log_lines.append(f"[WARN] {layer.name()}: {code}")

            field_names = list(descriptor.field_names)
            staged_dbf = os.path.join(self.temp_dir, plan.staged_basename + ".dbf")
            if plan.rename_map and os.path.isfile(staged_dbf):
                shapefile_io.rewrite_dbf_field_names(staged_dbf, field_names, plan.rename_map)

            dest_sld = os.path.join(self.temp_dir, plan.staged_basename + ".sld")
            sld_ok, sld_message = _export_sld(layer, dest_sld)
            self.sld_results.append((layer.name(), sld_ok, sld_message))
            if sld_ok:
                if plan.sld_rename_map:
                    shapefile_io.rewrite_sld_field_references(dest_sld, plan.sld_rename_map)
                shapefile_io.rewrite_unsupported_marks(dest_sld)

        if wms_urls:
            wms_file = os.path.join(self.temp_dir, "urls.wms")
            with open(wms_file, "w", encoding="utf-8") as f:
                f.write("\n".join(wms_urls))

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

    def start(self, generate=False, config_path=None):
        gispub_path = check_node_gispublisher()
        args = []

        self.generate = generate
        self._start_time = time.time()
        self.copy_layers_directly()
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

    def show_success_popup(self):
        if self.debug:
            self.progress_label.setText("GISPublisher finished ✅")
            self.output_text.appendPlainText("\n> Process completed successfully.")
            return

        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle("Process completed")

        if self.generate:
            msg_box.setText("The application was generated successfully.")
            open_button = msg_box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        else:
            text = "Deployment completed successfully."
            if self.resulting_host:
                text += f"\n\nThe application is available at:\n{self.resulting_host}"
            msg_box.setText(text)
            open_button = None

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
            self.progress_bar.setValue(100)
            self.progress_bar.setStyleSheet("")
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
