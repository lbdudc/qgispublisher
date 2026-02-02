import os, tempfile
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
        os.makedirs(os.path.join(self.temp_dir, "layers"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "charts"), exist_ok=True)
        self.process = None
        self.timer = None
        self.fake_progress = 0

    def start(self, generate=False):
        gispub_path = check_node_gispublisher()
        args = [self.temp_dir]
        if generate:
            args.append("-g")
        self.run_gispublisher(gispub_path, args)

    def run_gispublisher(self, gispub_path, args):
        self.progress_label.setText("Running GISPublisher...")
        self.progress_label.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.output_text.clear()
        self.output_text.appendPlainText("> Starting GISPublisher...\n")

        os.environ["PATH"] += os.pathsep + r"C:\Program Files\Docker\Docker\resources\bin"

        self.process = QProcess()
        self.process.setProgram(gispub_path)
        self.process.setArguments(args)
        self.process.setWorkingDirectory(self.output_dir)

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
