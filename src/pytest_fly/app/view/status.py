from collections import defaultdict
from enum import Enum
from datetime import timedelta

import humanize
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QWidget, QGridLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from _pytest.config import ExitCode

from ..preferences import get_pref
from ...common import PytestStatus, PytestProcessState, get_performance_core_count


class Columns(Enum):
    NAME = 0
    STATE = 1
    CPU = 2
    MEMORY = 3
    RUNTIME = 4


def set_widget_color(widget, value):
    pref = get_pref()
    palette = widget.palette()
    if value > pref.utilization_high_threshold:
        palette.setColor(QPalette.WindowText, QColor("red"))
    elif value > pref.utilization_low_threshold:
        palette.setColor(QPalette.WindowText, QColor("yellow"))
    else:
        palette.setColor(QPalette.WindowText, QColor("black"))
    widget.setPalette(palette)


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
        headers = ["Name", "State", "CPU", "Memory", "Runtime"]
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
                # test, so new row
                for column in Columns:
                    label = QLabel()
                    self.labels[test][column] = label
                    layout.addWidget(label, row_number, column.value)

            self.labels[test][Columns.NAME].setText(status.name)
            if status.state == PytestProcessState.FINISHED and status.exit_code is not None:
                palette = self.labels[test][Columns.STATE].palette()
                if status.exit_code == ExitCode.OK:
                    palette.setColor(QPalette.WindowText, QColor("green"))
                else:
                    palette.setColor(QPalette.WindowText, QColor("red"))
                self.labels[test][Columns.STATE].setText(status.exit_code.name)
                self.labels[test][Columns.STATE].setPalette(palette)
            else:
                self.labels[test][Columns.STATE].setText(status.state)
            if status.state != PytestProcessState.QUEUED:
                performance_core_count = get_performance_core_count()

                cpu_usage = self.max_cpu_usage[test] / performance_core_count
                set_widget_color(self.labels[test][Columns.CPU], cpu_usage)
                self.labels[test][Columns.CPU].setText(f"{cpu_usage:.2%}")

                memory_usage = self.max_memory_usage[test]
                set_widget_color(self.labels[test][Columns.MEMORY], memory_usage)
                self.labels[test][Columns.MEMORY].setText(f"{memory_usage:.2%}")

                if status.start is not None and status.end is not None:
                    runtime = status.end - status.start
                    self.labels[test][Columns.RUNTIME].setText(humanize.precisedelta(timedelta(seconds=runtime)))
