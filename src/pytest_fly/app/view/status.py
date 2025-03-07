from collections import defaultdict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QWidget

from .gui_util import PlainTextWidget
from ...common import PytestStatus


class Status(QGroupBox):

    def __init__(self):
        super().__init__()

        self.statuses = {}
        self.max_cpu_usage = defaultdict(float)
        self.max_memory_usage = defaultdict(float)

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
        for test, status in self.statuses.items():
            if (process_monitor_data := status.process_monitor_data) is not None:
                self.max_memory_usage[test] = max(process_monitor_data.memory_percent / 100.0, self.max_memory_usage[test])
                self.max_cpu_usage[test] = max(process_monitor_data.cpu_percent / 100.0, self.max_cpu_usage[test])
            lines.append(f"{status.name}: {status.state} (cpu={self.max_cpu_usage[test]},memory={self.max_memory_usage[test]})")

        self.test_widget.set_text("\n".join(lines))
