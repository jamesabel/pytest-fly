from PySide6.QtWidgets import QGroupBox, QVBoxLayout

from ..gui_util import PlainTextWidget
from ...model import exit_code_to_string, PytestStatus


class StatusWindow(QGroupBox):

    def __init__(self):
        super().__init__()
        self.statuses = []
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.status_widget = PlainTextWidget()
        layout.addWidget(self.status_widget)
        layout.addStretch()

    def update_status(self, status: PytestStatus):
        self.statuses.append(status)
        strings = [str((status.name, str(status.state), exit_code_to_string(status.exit_code))) for status in self.statuses]
        self.status_widget.set_text("\n".join(strings))
