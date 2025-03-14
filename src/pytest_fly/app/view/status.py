from collections import defaultdict
from enum import Enum
from datetime import timedelta

import humanize
from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QMenu
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPalette, QColor, QClipboard, QGuiApplication
from _pytest.config import ExitCode

from ..preferences import get_pref
from ...common import PytestStatus, PytestProcessState, get_performance_core_count


class Columns(Enum):
    NAME = 0
    STATE = 1
    CPU = 2
    MEMORY = 3
    RUNTIME = 4


def set_utilization_color(item: QTableWidgetItem, value: float):
    pref = get_pref()
    if value > pref.utilization_high_threshold:
        item.setForeground(QColor("red"))
    elif value > pref.utilization_low_threshold:
        item.setForeground(QColor("yellow"))
    else:
        # no change to color
        return


class Status(QGroupBox):

    def __init__(self):
        super().__init__()

        self.statuses = {}
        self.max_cpu_usage = defaultdict(float)
        self.max_memory_usage = defaultdict(float)

        self.setTitle("Tests")
        layout = QVBoxLayout()

        # Create a scroll area
        scroll_area = QScrollArea(parent=self)
        scroll_area.setWidgetResizable(True)

        # Create a table widget to hold the content
        self.table_widget = QTableWidget(parent=scroll_area)
        self.table_widget.setColumnCount(len(Columns))
        self.table_widget.setHorizontalHeaderLabels(["Name", "State", "CPU", "Memory", "Runtime"])
        self.table_widget.horizontalHeader().setStretchLastSection(True)
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)

        scroll_area.setWidget(self.table_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    def show_context_menu(self, position: QPoint):
        menu = QMenu()
        copy_action = menu.addAction("Copy")
        action = menu.exec_(self.table_widget.viewport().mapToGlobal(position))
        if action == copy_action:
            self.copy_selected_text()

    def copy_selected_text(self):
        selected_ranges = self.table_widget.selectedRanges()
        if selected_ranges:
            clipboard = QGuiApplication.clipboard()
            selected_text = []
            for selected_range in selected_ranges:
                for row in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                    row_data = []
                    for col in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                        item = self.table_widget.item(row, col)
                        if item is not None:
                            row_data.append(item.text())
                    selected_text.append(",".join(row_data))
            clipboard.setText("\n".join(selected_text))

    def reset(self):
        self.table_widget.setRowCount(0)
        self.statuses.clear()
        self.max_cpu_usage.clear()
        self.max_memory_usage.clear()

    def update_status(self, status: PytestStatus):
        self.statuses[status.name] = status

        row_number = list(self.statuses.keys()).index(status.name)
        if row_number >= self.table_widget.rowCount():
            self.table_widget.insertRow(row_number)

        if (process_monitor_data := status.process_monitor_data) is not None:
            self.max_memory_usage[status.name] = max(process_monitor_data.memory_percent / 100.0, self.max_memory_usage[status.name])
            self.max_cpu_usage[status.name] = max(process_monitor_data.cpu_percent / 100.0, self.max_cpu_usage[status.name])

        self.table_widget.setItem(row_number, Columns.NAME.value, QTableWidgetItem(status.name))
        state_item = QTableWidgetItem(status.state)
        if status.state == PytestProcessState.FINISHED and status.exit_code is not None:
            if status.exit_code == ExitCode.OK:
                state_item.setForeground(QColor("green"))
            else:
                state_item.setForeground(QColor("red"))
        self.table_widget.setItem(row_number, Columns.STATE.value, state_item)

        if status.state != PytestProcessState.QUEUED:
            performance_core_count = get_performance_core_count()

            cpu_usage = self.max_cpu_usage[status.name] / performance_core_count
            cpu_item = QTableWidgetItem(f"{cpu_usage:.2%}")
            set_utilization_color(cpu_item, cpu_usage)
            self.table_widget.setItem(row_number, Columns.CPU.value, cpu_item)

            memory_usage = self.max_memory_usage[status.name]
            memory_item = QTableWidgetItem(f"{memory_usage:.2%}")
            set_utilization_color(memory_item, memory_usage)
            self.table_widget.setItem(row_number, Columns.MEMORY.value, memory_item)

            if status.start is not None and status.end is not None:
                runtime = status.end - status.start
                self.table_widget.setItem(row_number, Columns.RUNTIME.value, QTableWidgetItem(humanize.precisedelta(timedelta(seconds=runtime))))

        # Resize columns to fit contents
        self.table_widget.resizeColumnsToContents()
