import time
from enum import Enum

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem, QMenu
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QGuiApplication

from ...preferences import get_pref
from ...interfaces import PyTestFlyExitCode
from ...tick_data import TickData
from ...gui.gui_util import tool_tip_limiter, format_runtime
from ...platform.platform_info import get_performance_core_count


class Columns(Enum):
    NAME = 0
    STATE = 1
    CPU = 2
    MEMORY = 3
    RUNTIME = 4
    COVERAGE = 5


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
        self.table_widget.setHorizontalHeaderLabels(["Name", "State", "CPU", "Memory", "Runtime", "Coverage"])
        self.table_widget.horizontalHeader().setStretchLastSection(True)
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)

        scroll_area.setWidget(self.table_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

    def show_context_menu(self, position: QPoint):
        """Show a right-click context menu allowing the user to copy pytest output.

        :param position: Click position relative to the table viewport.
        """
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
        """Clear all table rows."""
        self.table_widget.setRowCount(0)

    def update_tick(self, tick: TickData):
        """Refresh the table from pre-computed tick data."""

        self.table_widget.clearContents()
        self.table_widget.setRowCount(len(tick.infos_by_name))

        for row_number, test_name in enumerate(tick.infos_by_name):
            process_infos = tick.infos_by_name[test_name]
            pytest_run_state = tick.run_states[test_name]

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

        self.table_widget.resizeColumnsToContents()
