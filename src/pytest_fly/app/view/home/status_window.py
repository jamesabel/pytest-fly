from PySide6.QtWidgets import QGroupBox, QVBoxLayout

from ..gui_util import PlainTextWidget
from ...model import exit_code_to_string, PytestStatus, PytestKey


class StatusWindow(QGroupBox):

    def __init__(self):
        super().__init__()
        self.statuses = {}
        self.setTitle("Status")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.status_widget = PlainTextWidget()
        layout.addWidget(self.status_widget)
        layout.addStretch()

    def update_status(self, status: PytestStatus):
        pytest_key = PytestKey(name=status.name, state=status.state)
        self.statuses[pytest_key] = status
        lines = []
        for key, status in self.statuses.items():
            lines.append(str((key.name, str(key.state), exit_code_to_string(status.exit_code))))
        self.status_widget.set_text("\n".join(lines))
