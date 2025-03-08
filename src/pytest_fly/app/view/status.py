from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QWidget, QGridLayout, QLabel
from PySide6.QtCore import Qt
from collections import defaultdict
from enum import Enum
from ...common import PytestStatus, PytestProcessState


class Columns(Enum):
    NAME = 0
    STATE = 1
    CPU = 2
    MEMORY = 3


class Status(QGroupBox):

    def __init__(self):
        super().__init__()

        self.statuses = {}
        self.labels = defaultdict(dict)
        self.max_cpu_usage = defaultdict(float)
        self.max_memory_usage = defaultdict(float)

        self.setTitle("Tests")
        layout = QVBoxLayout()

        # Create a scroll area
        scroll_area = QScrollArea(parent=self)
        scroll_area.setWidgetResizable(True)

        # Create a widget to hold the content
        self.content_widget = QWidget(parent=scroll_area)
        content_layout = QGridLayout(self.content_widget)
        content_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.content_widget.setLayout(content_layout)

        # Add header row
        headers = ["Name", "State", "CPU", "Memory"]
        for col, header in enumerate(headers):
            header_label = QLabel(header)
            header_label.setStyleSheet("font-weight: bold;")
            content_layout.addWidget(header_label, 0, col)

        scroll_area.setWidget(self.content_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    def reset(self):
        layout = self.content_widget.layout()
        for row_number, test in enumerate(self.statuses, start=1):
            for column in Columns:
                label = self.labels[test][column]
                layout.removeWidget(label)
                label.deleteLater()
        self.statuses = {}
        self.labels = defaultdict(dict)
        self.max_cpu_usage = defaultdict(float)
        self.max_memory_usage = defaultdict(float)

    def update_status(self, status: PytestStatus):
        self.statuses[status.name] = status

        layout = self.content_widget.layout()
        for row_number, test in enumerate(self.statuses, start=1):
            status = self.statuses[test]
            if (process_monitor_data := status.process_monitor_data) is not None:
                self.max_memory_usage[test] = max(process_monitor_data.memory_percent / 100.0, self.max_memory_usage[test])
                self.max_cpu_usage[test] = max(process_monitor_data.cpu_percent / 100.0, self.max_cpu_usage[test])

            if test not in self.labels:
                for column in Columns:
                    label = QLabel()
                    self.labels[test][column] = label
                    layout.addWidget(label, row_number, column.value)

            self.labels[test][Columns.NAME].setText(status.name)
            self.labels[test][Columns.STATE].setText(status.state)
            if status.state != PytestProcessState.QUEUED:
                self.labels[test][Columns.CPU].setText(f"{self.max_cpu_usage[test]:.2}")
                self.labels[test][Columns.MEMORY].setText(f"{self.max_memory_usage[test]:.2%}")
