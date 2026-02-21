import time
from collections import defaultdict
from enum import Enum

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem, QMenu
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QGuiApplication

from ...preferences import get_pref
from ...interfaces import PytestProcessInfo, PyTestFlyExitCode
from ...pytest_runner.pytest_runner import PytestRunState
from ...gui.gui_util import tool_tip_limiter


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
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)

        scroll_area.setWidget(self.table_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    # python
    def show_context_menu(self, position: QPoint):
        menu = QMenu()
        copy_tooltip_action = menu.addAction("Copy Pytest Output")
        action = menu.exec_(self.table_widget.viewport().mapToGlobal(position))

        if action == copy_tooltip_action:
            # try the item under the mouse; fallback to current item
            item = self.table_widget.itemAt(position)
            if item is None:
                item = self.table_widget.currentItem()
            if item is not None:
                tooltip = item.toolTip()
                # fallback to ItemDataRole if toolTip() is empty
                if not tooltip:
                    tooltip = item.data(Qt.ItemDataRole.ToolTipRole) or ""
                if tooltip:
                    clipboard = QGuiApplication.clipboard()
                    clipboard.setText(tooltip)

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
            state_text = pytest_run_state.get_string()
            state_item.setText(state_text)
            state_item.setForeground(pytest_run_state.get_qt_table_color())

            if len(process_infos) > 1 and process_infos[-1].output is not None:
                tooltip_text = tool_tip_limiter(process_infos[-1].output)
            else:
                tooltip_text = ""
            state_item.setToolTip(tooltip_text)
            state_item.setData(Qt.ItemDataRole.ToolTipRole, tooltip_text)

            self.table_widget.setItem(row_number, Columns.STATE.value, state_item)

            # Find the timestamp when the test started running and the final completed entry
            start_time = None
            final_info = None
            for info in process_infos:
                if info.pid is not None and start_time is None:
                    start_time = info.time_stamp
                if info.exit_code != PyTestFlyExitCode.NONE:
                    final_info = info

            # Runtime: elapsed from first "running" entry; live while still running
            if start_time is not None:
                end_time = final_info.time_stamp if final_info is not None else time.time()
                runtime_seconds = end_time - start_time
                if runtime_seconds < 60:
                    runtime_text = f"{runtime_seconds:.1f}s"
                else:
                    runtime_text = f"{int(runtime_seconds // 60)}m {int(runtime_seconds % 60)}s"
            else:
                runtime_text = ""

            # CPU and Memory: from the peak values recorded in the final DB entry
            cpu_text = f"{final_info.cpu_percent:.1f}%" if (final_info is not None and final_info.cpu_percent is not None) else ""
            memory_text = f"{final_info.memory_percent:.2f}%" if (final_info is not None and final_info.memory_percent is not None) else ""

            cpu_item = QTableWidgetItem(cpu_text)
            if final_info is not None and final_info.cpu_percent is not None:
                set_utilization_color(cpu_item, final_info.cpu_percent / 100.0)
            self.table_widget.setItem(row_number, Columns.CPU.value, cpu_item)

            self.table_widget.setItem(row_number, Columns.MEMORY.value, QTableWidgetItem(memory_text))
            self.table_widget.setItem(row_number, Columns.RUNTIME.value, QTableWidgetItem(runtime_text))

        # Resize columns to fit contents
        self.table_widget.resizeColumnsToContents()
