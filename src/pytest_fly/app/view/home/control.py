from pathlib import Path

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton
from PySide6.QtCore import QObject, QThread, Signal

from ...controller.pytest_runner import PytestRunnerWorker
from ... import get_logger

log = get_logger()


# class RunButtonClickedWorker(QObject):
#
#     update_signal = Signal(str)
#
#     def __init__(self):
#         super().__init__()
#         self.runner = None
#
#     def run(self):
#
#         self.runner = PytestRunner([Path("tests", "test_sleep.py")])
#         self.runner.start()
#         while self.runner.isRunning():
#             statuses = self.runner.get_statuses()
#             statuses_strings = [f"{status.name=},{status.running=},{status.exit_code=}" for status in statuses]
#             update_string = "\n".join(statuses_strings)
#             print(f"ControlWindow.run: {update_string}")
#             self.update_signal.emit(update_string)
#             self.runner.wait(3 * 1000)
#         statuses = self.runner.get_statuses()
#         statuses_strings = [f"{status.name=},{status.running=},{status.exit_code=}" for status in statuses]
#         update_string = "\n".join(statuses_strings)
#         print(f"ControlWindow.run: {update_string}")
#         self.update_signal.emit(update_string)


class ControlWindow(QGroupBox):

    def __init__(self, update_callback: callable):
        super().__init__()
        self.update_callback = update_callback
        self.setTitle("Control")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self.run_button_clicked)
        layout.addWidget(self.run_button)
        layout.addStretch()
        self.run_button_thread = None
        self.run_button_worker = None

    def run_button_clicked(self):
        self.run_button_thread = QThread()
        self.run_button_worker = PytestRunnerWorker([Path("tests", "test_sleep.py")])
        self.run_button_worker.moveToThread(self.run_button_thread)
        self.run_button_thread.started.connect(self.run_button_worker.process)
        self.run_button_worker.finished.connect(self.run_button_thread.quit)
        self.run_button_thread.finished.connect(self.run_button_thread.deleteLater)
        self.run_button_worker.update.connect(self.update_callback)
        if not self.run_button_thread.isRunning():
            self.run_button_thread.start()
