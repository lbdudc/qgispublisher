import os, tempfile
from PyQt5.QtCore import QProcess, QTimer
from ..core.dependencies_checker import check_node_gispublisher

class GISPublisherRunner:

    def __init__(self, layers, output_dir, progress_label, progress_bar, parent=None, finished_callback=None):
        self.layers = layers
        self.output_dir = output_dir
        self.progress_label = progress_label
        self.progress_bar = progress_bar
        self.parent = parent
        self.finished_callback = finished_callback
        self.temp_dir = tempfile.mkdtemp(prefix="qgis_gispublisher_")
        os.makedirs(os.path.join(self.temp_dir, "layers"), exist_ok=True)
        os.makedirs(os.path.join(self.temp_dir, "charts"), exist_ok=True)
        self.process = None
        self.timer = None
        self.fake_progress = 0

    def start(self):
        gispub_path = check_node_gispublisher()
        self.run_gispublisher(gispub_path)

    def run_gispublisher(self, gispub_path):
        if self.parent:
            self.parent.generateButton.setVisible(False)
            self.parent.cancelButton.setVisible(False)

        self.progress_label.setText("Running GISPublisher...")
        self.progress_label.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.process = QProcess()
        self.process.setProgram(gispub_path)
        self.process.setArguments(["-g", self.temp_dir])
        self.process.setWorkingDirectory(self.output_dir)

        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.finished)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_fake_progress)
        self.timer.start(2000)

        self.process.start()

    def update_fake_progress(self):
        if self.fake_progress < 90:
            self.fake_progress += 2
            self.progress_bar.setValue(self.fake_progress)
        else:
            self.timer.stop()

    def handle_stdout(self):
        text = self.process.readAllStandardOutput().data().decode()
        self.progress_label.setText(self.progress_label.text() + "\n" + text)
        self.progress_bar.setValue(min(self.progress_bar.value() + 1, 100))

    def handle_stderr(self):
        text = self.process.readAllStandardError().data().decode()
        self.progress_label.setText(self.progress_label.text() + "\n" + text)

    def finished(self):
        self.timer.stop()
        self.progress_bar.setValue(100)
        self.progress_label.setText("GISPublisher finished ✅")
        if self.parent:
            self.parent.generateButton.setVisible(True)
            self.parent.cancelButton.setVisible(True)
        if self.finished_callback:
            self.finished_callback()
