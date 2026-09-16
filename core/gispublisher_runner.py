import os, tempfile, pathlib, shutil, urllib.parse
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from qgis.core import QgsMapLayer
from ..core.dependencies_checker import check_node_gispublisher

class GISPublisherRunner:

    def __init__(self, layers, output_dir, progress_label, progress_bar, output_text, parent=None, finished_callback=None, chart_folder=None, chart_items=None, model_folder=None, model_items=None, debug=False):
        self.layers = layers
        self.output_dir = output_dir
        self.progress_label = progress_label
        self.progress_bar = progress_bar
        self.output_text = output_text
        self.parent = parent
        self.finished_callback = finished_callback
        self.chart_folder = chart_folder
        # None means "include everything in the folder"; a list restricts to those names.
        self.chart_items = chart_items
        self.model_folder = model_folder
        self.model_items = model_items
        self.temp_dir = tempfile.mkdtemp(prefix="qgis_gispublisher_")
        self.charts_temp_dir = os.path.join(self.temp_dir, "charts")
        os.makedirs(self.charts_temp_dir, exist_ok=True)
        self.models_temp_dir = os.path.join(self.temp_dir, "models")
        os.makedirs(self.models_temp_dir, exist_ok=True)
        self.process = None
        self.debug = debug
        self.cancelled = False

    def copy_layers_directly(self):
        wms_urls = []

        for layer in self.layers:
            # Raster Layer
            if layer.type() == QgsMapLayer.RasterLayer:
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

            # Vector Layer — strip QGIS URI suffix (e.g. |layername=...)
            source = pathlib.Path(layer.source().split("|")[0]).resolve()
            base = source.with_suffix("")

            for ext in [".shp", ".dbf", ".shx", ".prj", ".cpg"]:
                file = base.with_suffix(ext)
                if file.exists():
                    shutil.copy(file, self.temp_dir)

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
                dst_path = os.path.join(self.charts_temp_dir, item)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)

    def copy_model_folder(self):
        if self.model_folder and os.path.exists(self.model_folder):
            for item in os.listdir(self.model_folder):
                if self.model_items is not None and item not in self.model_items:
                    continue
                src_path = os.path.join(self.model_folder, item)
                dst_path = os.path.join(self.models_temp_dir, item)
                if os.path.isfile(src_path) and src_path.endswith(".model3"):
                    shutil.copy2(src_path, dst_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)

    def start(self, generate=False, config_path=None):
        gispub_path = check_node_gispublisher()
        args = []

        self.generate = generate
        self.copy_layers_directly()
        self.copy_chart_folder()
        self.copy_model_folder()

        if generate:
            shapefiles_folder = self.temp_dir
            args.append(shapefiles_folder)
            args.append("-g")
            working_dir = self.output_dir
        elif config_path:  # deploy
            shapefiles_folder = self.temp_dir
            config_path = pathlib.Path(config_path)

            args.append(shapefiles_folder)
            args.append("--config")
            args.append(config_path.name)          
            working_dir = str(config_path.parent)
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
        if self.process and self.process.state() != QProcess.NotRunning:
            self.cancelled = True
            self.process.kill()

    def handle_stdout(self):
        if self.output_text:
            text = bytes(self.process.readAllStandardOutput()).decode()
            if text.strip():
                self.output_text.appendPlainText(text.rstrip())

    def handle_stderr(self):
        if self.output_text:
            text = bytes(self.process.readAllStandardError()).decode()
            if text.strip():
                self.output_text.appendPlainText(f"[ERROR] {text.rstrip()}")
    
    def show_error_popup(self, message=None):
        if self.debug:
            self.progress_label.setText("GISPublisher finished with errors ❌")
            self.output_text.appendPlainText(f"\n> ERROR: {message or 'Execution failed'}")
            return

        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("GISPublisher Error")
        msg_box.setText("An error occurred during GISPublisher execution.")
        if message:
            msg_box.setInformativeText(message)
        msg_box.exec_()

    def show_success_popup(self):
        if self.debug:
            self.progress_label.setText("GISPublisher finished ✅")
            self.output_text.appendPlainText("\n> Process completed successfully.")
            return

        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle("Process completed")

        if self.generate:
            msg_box.setText("The application was generated successfully.")
            open_button = msg_box.addButton("Open folder", QMessageBox.ActionRole)
        else:
            msg_box.setText("Deployment completed successfully.")
            open_button = None

        msg_box.addButton(QMessageBox.Ok)
        msg_box.exec_()

        if self.generate and msg_box.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

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

        if self.finished_callback:
            self.finished_callback()
