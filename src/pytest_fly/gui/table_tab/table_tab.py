from collections import defaultdict
from enum import Enum

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem, QMenu
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QGuiApplication

from ...preferences import get_pref
from ...interfaces import PytestProcessInfo
from ...pytest_runner.pytest_runner import PytestRunState


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

        self.table_widget.clearContents()

        processes_infos = defaultdict(list)
        for pytest_process_info in pytest_process_infos:
            processes_infos[pytest_process_info.name].append(pytest_process_info)

        self.table_widget.setRowCount(len(processes_infos))

        for row_number, test_name in enumerate(processes_infos):
            process_infos = processes_infos[test_name]

            pytest_run_state = PytestRunState(process_infos)

            self.table_widget.setItem(row_number, Columns.NAME.value, QTableWidgetItem(pytest_run_state.get_name()))

            state_item = QTableWidgetItem()
            state_item.setText(pytest_run_state.get_string())
            state_item.setForeground(pytest_run_state.get_qt_table_color())
            self.table_widget.setItem(row_number, Columns.STATE.value, state_item)

        # Resize columns to fit contents
        self.table_widget.resizeColumnsToContents()
