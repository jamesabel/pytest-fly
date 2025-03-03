from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QWidget

from .gui_util import PlainTextWidget
from ...common import PytestStatus


class Status(QGroupBox):

    def __init__(self):
        super().__init__()

        self.statuses = {}

        self.setTitle("Tests")
        layout = QVBoxLayout()

        # Create a scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # Create a widget to hold the content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        self.test_widget = PlainTextWidget()
        content_layout.addWidget(self.test_widget)
        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    def update_status(self, status: PytestStatus):

        self.statuses[status.name] = status

        lines = []
        for status in self.statuses.values():
            lines.append(f"{status.name}: {status.state}")

        self.test_widget.set_text("\n".join(lines))
