import os, tempfile, pathlib, shutil
from PyQt5.QtCore import QProcess, QTimer
from ..core.dependencies_checker import check_node_gispublisher

class GISPublisherRunner:

    def __init__(self, layers, output_dir, progress_label, progress_bar, output_text, parent=None, finished_callback=None):
        self.layers = layers
        self.output_dir = output_dir
        self.progress_label = progress_label
        self.progress_bar = progress_bar
        self.output_text = output_text
        self.parent = parent
        self.finished_callback = finished_callback
        self.temp_dir = tempfile.mkdtemp(prefix="qgis_gispublisher_")
        os.makedirs(os.path.join(self.temp_dir, "charts"), exist_ok=True)
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

    def start(self, generate=False, config_path=None):
        gispub_path = check_node_gispublisher()
        args = []

        self.copy_layers_directly()

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
        self.progress_bar.setValue(0)

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
        self.progress_bar.setValue(min(self.progress_bar.value() + 1, 100))

    def handle_stderr(self):
        text = bytes(self.process.readAllStandardError()).decode()
        if text.strip():
            self.output_text.appendPlainText(f"[ERROR] {text.rstrip()}")

    def finished(self):
        if self.timer:
            self.timer.stop()

        self.progress_bar.setValue(100)
        self.progress_label.setText("GISPublisher finished ✅")
        self.output_text.appendPlainText("\n> Process finished.")

        if self.finished_callback:
            self.finished_callback()
