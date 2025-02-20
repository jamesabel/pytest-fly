from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton
from PySide6.QtCore import QThread, QCoreApplication, QEventLoop


from ...controller.pytest_runner import PytestRunnerWorker
from ... import get_logger

log = get_logger()


class ControlWindow(QGroupBox):

    def __init__(self, parent, update_callback: callable):
        super().__init__(parent)
        self.update_callback = update_callback
        self.setTitle("Control")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.run_button = QPushButton("Run")
        layout.addWidget(self.run_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        layout.addStretch()
        self.run_button.clicked.connect(self.run)
        self.stop_button.clicked.connect(self.stop)
        self.pytest_runner_thread = None
        self.pytest_runner_worker = None

    def run(self):
        if self.pytest_runner_thread is None and self.pytest_runner_worker is None:
            self.pytest_runner_thread = QThread(self)  # work will be done in this thread
            # I'd like the thread to have some name, so use the name of the worker it'll be moved to
            self.pytest_runner_thread.setObjectName(PytestRunnerWorker.__class__.__name__)
            self.pytest_runner_worker = PytestRunnerWorker()
            self.pytest_runner_worker.moveToThread(self.pytest_runner_thread)  # move worker to thread
            self.pytest_runner_worker.request_exit_signal.connect(self.pytest_runner_thread.quit)
            self.pytest_runner_worker.update_signal.connect(self.update_callback)
            self.pytest_runner_thread.started.connect(self.pytest_runner_worker.run)
            self.pytest_runner_thread.start()
        self.run_button.setEnabled(False)
        self.pytest_runner_worker.request_run()
        self.stop_button.setEnabled(True)

    def stop(self):
        self.stop_button.setEnabled(False)
        self.pytest_runner_worker.request_stop()
        self.run_button.setEnabled(True)

    def exit_request(self):
        if self.pytest_runner_worker is not None:
            self.pytest_runner_worker.request_stop()
            QCoreApplication.processEvents()  # ensure the worker gets the request to stop signal
            self.pytest_runner_worker.request_exit_signal.emit()
            # ensure we don't get a QThread still running error
            while self.pytest_runner_thread.isRunning():
                self.pytest_runner_thread.wait(1000)
                QCoreApplication.processEvents()
