from PySide6.QtWidgets import QGroupBox, QVBoxLayout
from PySide6.QtCore import Signal

from ..gui_util import PlainTextWidget


class StatusWindow(QGroupBox):

    _status_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.status_widget = PlainTextWidget()
        layout.addWidget(self.status_widget)
        layout.addStretch()
        self._status_signal.connect(self._update_status)

    def update_status(self, status: str):
        self._status_signal.emit(status)

    def _update_status(self, status: str):
        self._status_signal.emit(status)
