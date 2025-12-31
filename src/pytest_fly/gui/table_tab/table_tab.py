from collections import defaultdict
from enum import Enum

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem, QMenu
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QGuiApplication
from pytest import ExitCode

from ...preferences import get_pref
from ...interfaces import exit_code_to_string, PytestProcessInfo


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


class TableTab(QGroupBox):

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

    def update_pytest_process_info(self, pytest_process_infos: list[PytestProcessInfo]):

        self.table_widget.clear()

        # get the most recent state for each test
        most_recent_process_infos = {}
        for pytest_process_info in pytest_process_infos:
            most_recent_process_infos[pytest_process_info.name] = pytest_process_info

        self.table_widget.setRowCount(len(most_recent_process_infos))

        for row_number, test in enumerate(most_recent_process_infos):
            process_info = most_recent_process_infos[test]
            self.table_widget.setItem(row_number, Columns.NAME.value, QTableWidgetItem(process_info.name))

            state_item = QTableWidgetItem()
            if process_info.pid is None:
                state_item.setText("Queued")
                state_item.setForeground(QColor("gray"))
            elif process_info.exit_code is None:
                state_item.setText("Running")
                state_item.setForeground(QColor("blue"))
            elif process_info.exit_code == ExitCode.OK:
                state_item.setText("Pass")
                state_item.setForeground(QColor("green"))
            else:
                exit_code_string = exit_code_to_string(process_info.exit_code)
                state_item.setText(f"Fail ({exit_code_string})")
                state_item.setForeground(QColor("red"))
            self.table_widget.setItem(row_number, Columns.STATE.value, state_item)

        # Resize columns to fit contents
        self.table_widget.resizeColumnsToContents()
