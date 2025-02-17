from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton

from ...controller.pytest_runner import PytestRunner
from ... import get_logger

log = get_logger()


class ControlWindow(QGroupBox):
    def __init__(self, update_callback: callable):
        super().__init__()
        self.update_callback = update_callback
        self.setTitle("Control")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.run)
        layout.addWidget(self.run_button)
        layout.addStretch()
        self.runner = None

    def run(self):
        if self.runner is not None and self.runner.isRunning():
            log.warning(f"Runner is already running")
        else:
            print("Starting runner")
            self.runner = PytestRunner(self.update_callback)
            self.runner.start()
