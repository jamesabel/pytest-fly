"""
Table tab — per-test status grid showing state, CPU, memory, runtime,
coverage, and last-pass information.
"""

import time
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QGroupBox, QMenu, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout

from ...gui.gui_util import format_runtime, tool_tip_limiter
from ...interfaces import PyTestFlyExitCode, PytestRunnerState
from ...platform.platform_info import get_performance_core_count
from ...preferences import get_pref
from ...tick_data import TickData


class Columns(Enum):
    NAME = 0
    STATE = 1
    CPU = 2
    MEMORY = 3
    RUNTIME = 4
    COVERAGE = 5
    LAST_PASS_START = 6
    LAST_PASS_DURATION = 7


def set_utilization_color(item: QTableWidgetItem, value: float):
    """
    Colorize a table cell based on utilization thresholds from user preferences.

    Red if above the high threshold, yellow if above the low threshold,
    otherwise the default color is kept.

    :param item: The table-widget item to colorize.
    :param value: Utilization value in the range ``[0.0, 1.0]``.
    """
    pref = get_pref()
    if value > pref.utilization_high_threshold:
        item.setForeground(QColor("red"))
    elif value > pref.utilization_low_threshold:
        item.setForeground(QColor("yellow"))
    else:
        return


class TableTab(QGroupBox):
    """Tab showing a per-test table with state, CPU, memory, and runtime columns."""

    force_stop_test_requested = Signal(str)  # emits the test node_id

    def __init__(self):
        super().__init__()

        self.setTitle("Tests")
        layout = QVBoxLayout()

        # Create a scroll area
        scroll_area = QScrollArea(parent=self)
        scroll_area.setWidgetResizable(True)

        # Create a table widget to hold the content
        self.table_widget = QTableWidget(parent=scroll_area)
        self.table_widget.setColumnCount(len(Columns))
        self.table_widget.setHorizontalHeaderLabels(["Name", "State", "CPU", "Memory", "Runtime", "Coverage", "Last Pass Start", "Last Pass Duration"])
        self.table_widget.horizontalHeader().setStretchLastSection(True)
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)

        scroll_area.setWidget(self.table_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        self._current_run_states: dict = {}

    def show_context_menu(self, position: QPoint):
        """Show a right-click context menu allowing the user to copy pytest output or force-stop a running test.

        :param position: Click position relative to the table viewport.
        """
        item = self.table_widget.itemAt(position)
        if item is None:
            item = self.table_widget.currentItem()

        # Determine the test node_id and state for the right-clicked row
        row = item.row() if item is not None else -1
        test_node_id = None
        is_running = False
        if row >= 0:
            name_item = self.table_widget.item(row, Columns.NAME.value)
            if name_item is not None:
                test_node_id = name_item.data(Qt.ItemDataRole.UserRole)
            if test_node_id is not None and test_node_id in self._current_run_states:
                is_running = self._current_run_states[test_node_id].get_state() == PytestRunnerState.RUNNING

        menu = QMenu()
        copy_tooltip_action = menu.addAction("Copy Pytest Output")
        force_stop_action = None
        if test_node_id is not None and is_running:
            force_stop_action = menu.addAction("Force Stop")

        # Save row/col before exec_() — the nested event loop lets timer
        # refreshes destroy the underlying C++ QTableWidgetItem.
        item_row = item.row() if item is not None else -1
        item_col = item.column() if item is not None else -1

        action = menu.exec_(self.table_widget.viewport().mapToGlobal(position))

        if action == copy_tooltip_action:
            # Re-fetch the item after exec_() to avoid stale C++ pointer
            if item_row >= 0 and item_col >= 0:
                item = self.table_widget.item(item_row, item_col)
            if item is not None:
                try:
                    tooltip = item.toolTip()
                except RuntimeError:
                    return  # item's C++ object was deleted between retrieval and access

                # fallback to ItemDataRole if toolTip() is empty
                if not tooltip:
                    tooltip = item.data(Qt.ItemDataRole.ToolTipRole) or ""
                if tooltip:
                    clipboard = QGuiApplication.clipboard()
                    clipboard.setText(tooltip)
        elif action is not None and action == force_stop_action:
            self.force_stop_test_requested.emit(test_node_id)

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
        """Clear all table rows."""
        self.table_widget.setRowCount(0)

    def update_tick(self, tick: TickData):
        """Refresh the table from pre-computed tick data."""

        self._current_run_states = tick.run_states

        self.table_widget.clearContents()
        self.table_widget.setRowCount(len(tick.infos_by_name))

        for row_number, test_name in enumerate(sorted(tick.infos_by_name)):
            process_infos = tick.infos_by_name[test_name]
            pytest_run_state = tick.run_states[test_name]

            name_item = QTableWidgetItem(pytest_run_state.get_name())
            name_item.setData(Qt.ItemDataRole.UserRole, test_name)  # store node_id for context menu
            self.table_widget.setItem(row_number, Columns.NAME.value, name_item)

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
                runtime_text = format_runtime(end_time - start_time)
            else:
                runtime_text = ""

            # CPU and Memory
            p_cores = get_performance_core_count()
            if final_info is not None and final_info.cpu_percent is not None:
                cpu_normalized = min(final_info.cpu_percent / p_cores, 100.0)
                cpu_text = f"{cpu_normalized:.1f}%"
            else:
                cpu_normalized = None
                cpu_text = ""
            memory_text = f"{final_info.memory_percent:.2f}%" if (final_info is not None and final_info.memory_percent is not None) else ""

            cpu_item = QTableWidgetItem(cpu_text)
            if cpu_normalized is not None:
                set_utilization_color(cpu_item, cpu_normalized / 100.0)
            self.table_widget.setItem(row_number, Columns.CPU.value, cpu_item)
            self.table_widget.setItem(row_number, Columns.MEMORY.value, QTableWidgetItem(memory_text))
            self.table_widget.setItem(row_number, Columns.RUNTIME.value, QTableWidgetItem(runtime_text))

            # Per-test coverage
            coverage_pct = tick.per_test_coverage.get(test_name)
            coverage_text = f"{coverage_pct:.1%}" if coverage_pct is not None else ""
            self.table_widget.setItem(row_number, Columns.COVERAGE.value, QTableWidgetItem(coverage_text))

            # Last pass data (persists across runs)
            last_pass = tick.last_pass_data.get(test_name)
            if last_pass is not None:
                last_pass_start_ts, last_pass_duration = last_pass
                last_pass_start_text = datetime.fromtimestamp(last_pass_start_ts).strftime("%Y-%m-%d %H:%M:%S")
                last_pass_duration_text = format_runtime(last_pass_duration)
            else:
                last_pass_start_text = ""
                last_pass_duration_text = ""
            self.table_widget.setItem(row_number, Columns.LAST_PASS_START.value, QTableWidgetItem(last_pass_start_text))
            self.table_widget.setItem(row_number, Columns.LAST_PASS_DURATION.value, QTableWidgetItem(last_pass_duration_text))

        self.table_widget.resizeColumnsToContents()
