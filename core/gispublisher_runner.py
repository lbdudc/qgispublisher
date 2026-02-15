import os, tempfile, pathlib, shutil
from PyQt5.QtCore import QProcess, QTimer
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from ..core.dependencies_checker import check_node_gispublisher

class GISPublisherRunner:

    def __init__(self, layers, output_dir, progress_label, progress_bar, output_text, parent=None, finished_callback=None, chart_folder=None):
        self.layers = layers
        self.output_dir = output_dir
        self.progress_label = progress_label
        self.progress_bar = progress_bar
        self.output_text = output_text
        self.parent = parent
        self.finished_callback = finished_callback
        self.chart_folder = chart_folder
        self.temp_dir = tempfile.mkdtemp(prefix="qgis_gispublisher_")
        self.charts_temp_dir = os.path.join(self.temp_dir, "charts")
        os.makedirs(self.charts_temp_dir, exist_ok=True)
        self.process = None
        self.timer = None
        self.fake_progress = 0

    def copy_layers_directly(self):
        for layer in self.layers:
            source = pathlib.Path(layer.source()).resolve()
            base = source.with_suffix("")

            for ext in [".shp", ".dbf", ".shx", ".prj", ".cpg"]:
                file = base.with_suffix(ext)
                if file.exists():
                    shutil.copy(file, self.temp_dir)

    def copy_chart_folder(self):
        if self.chart_folder and os.path.exists(self.chart_folder):
            for item in os.listdir(self.chart_folder):
                src_path = os.path.join(self.chart_folder, item)
                dst_path = os.path.join(self.charts_temp_dir, item)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path, dirs_exist_ok=True)

    def start(self, generate=False, config_path=None):
        gispub_path = check_node_gispublisher()
        args = []

        self.generate = generate
        self.copy_layers_directly()
        self.copy_chart_folder()

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
        self.progress_label.setText("Ejecutando GISPublisher...")
        self.progress_label.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.output_text.clear()
        self.output_text.appendPlainText("> Iniciando GISPublisher...\n")

        self.process = QProcess()
        self.process.setProgram(gispub_path)
        self.process.setArguments(args)

        if working_dir:
            self.process.setWorkingDirectory(working_dir)

        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.finished)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_fake_progress)
        self.timer.start(1000)

        self.process.start()

    def update_fake_progress(self):
        if self.fake_progress < 90:
            self.fake_progress += 2
            self.progress_bar.setValue(self.fake_progress)
        else:
            self.timer.stop()

    def handle_stdout(self):
        text = bytes(self.process.readAllStandardOutput()).decode()
        if text.strip():
            self.output_text.appendPlainText(text.rstrip())
        self.progress_bar.setValue(min(self.progress_bar.value() + 1, 90))

    def handle_stderr(self):
        text = bytes(self.process.readAllStandardError()).decode()
        if text.strip():
            self.output_text.appendPlainText(f"[ERROR] {text.rstrip()}")
    
    def show_error_popup(self, message=None):
        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("Error en GISPublisher")
        msg_box.setText("Ha ocurrido un error durante la ejecución de GISPublisher.")
        if message:
            msg_box.setInformativeText(message)
        msg_box.exec_()

    def show_success_popup(self):
        msg_box = QMessageBox(self.parent)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle("Proceso completado")

        if self.generate:
            msg_box.setText("El producto se ha generado correctamente.")
            open_button = msg_box.addButton("Abrir carpeta", QMessageBox.ActionRole)
        else:
            msg_box.setText("El despliegue se ha completado correctamente.")
            open_button = None

        msg_box.addButton(QMessageBox.Ok)
        msg_box.exec_()

        if self.generate and msg_box.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

    def finished(self, exitCode, exitStatus):
        if self.timer:
            self.timer.stop()

        if exitCode == 0:
            self.progress_bar.setValue(100)
            self.progress_bar.setStyleSheet("")
            self.progress_label.setText("GISPublisher finalizado ✅")
            self.output_text.appendPlainText("\n> Proceso finalizado correctamente.")
            self.show_success_popup()
        else:
            self.progress_label.setText("GISPublisher falló ❌")
            self.output_text.appendPlainText(f"\n> Proceso finalizado con errores (código de salida {exitCode}).")
            self.show_error_popup()

        if self.finished_callback:
            self.finished_callback()
