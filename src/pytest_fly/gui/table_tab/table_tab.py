"""
Table tab — per-test status grid showing state, CPU, memory, runtime,
coverage, and last-pass information.
"""

import time
from datetime import datetime
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import QGroupBox, QMenu, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout
from typeguard import typechecked

from ...gui.gui_util import format_runtime, tool_tip_limiter
from ...interfaces import PyTestFlyExitCode, PytestRunnerState
from ...platform.platform_info import get_performance_core_count
from ...preferences import get_pref
from ...pytest_runner.live_output import read_live_output
from ...pytest_runner.process_monitor import normalize_cpu_percent
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


def set_utilization_color(item: QTableWidgetItem, value: float, high_threshold: float, low_threshold: float):
    """
    Colorize a table cell based on utilization thresholds.

    Red if above the high threshold, yellow if above the low threshold,
    otherwise the default foreground is restored (important for in-place
    updates where a previously-colored item may drop back below threshold).

    :param item: The table-widget item to colorize.
    :param value: Utilization value in the range ``[0.0, 1.0]``.
    :param high_threshold: Utilization threshold above which the cell is red.
    :param low_threshold: Utilization threshold above which the cell is yellow.
    """
    if value > high_threshold:
        item.setForeground(QColor("red"))
    elif value > low_threshold:
        item.setForeground(QColor("yellow"))
    else:
        item.setForeground(QBrush())


_SORT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1


class _SortableItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by a numeric key stored at _SORT_KEY_ROLE when present.

    Falls back to text comparison directly (not super().__lt__) because routing through
    QTableWidgetItem's C++ operator< from a Python subclass has caused access violations
    on Windows/PySide6 when no numeric key is set.
    """

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, QTableWidgetItem):
            a = self.data(_SORT_KEY_ROLE)
            b = other.data(_SORT_KEY_ROLE)
            if a is not None and b is not None:
                return a < b
            return self.text() < other.text()
        return NotImplemented


class TableTab(QGroupBox):
    """Tab showing a per-test table with state, CPU, memory, and runtime columns."""

    force_stop_test_requested = Signal(str)  # emits the test node_id

    @typechecked
    def __init__(self, data_dir: Path):
        super().__init__()

        self._data_dir = data_dir

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
        self.table_widget.horizontalHeader().setSortIndicatorShown(True)
        self.table_widget.horizontalHeader().sectionDoubleClicked.connect(self._on_header_double_clicked)
        self.table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)

        scroll_area.setWidget(self.table_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        self._current_run_states: dict = {}
        self._current_infos_by_name: dict = {}  # test node_id -> list[PytestProcessInfo]; source for full (untruncated) copy-to-clipboard
        self._row_by_name: dict[str, int] = {}  # test_name -> row index, for in-place updates
        self._sort_column: int | None = None
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

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
            # Prefer the untruncated output from the latest PytestProcessInfo so
            # users get the full pytest output (not the tooltip-limited view).
            output_text = ""
            if test_node_id is not None:
                infos = self._current_infos_by_name.get(test_node_id, [])
                for info in reversed(infos):
                    if info.output:
                        output_text = info.output
                        break

            # If no completed-output record exists yet but the test is currently
            # running, pull the live log tail directly from disk.
            if not output_text and is_running and test_node_id is not None:
                live_text = read_live_output(self._data_dir, test_node_id, max_bytes=10_000_000)
                if live_text:
                    output_text = live_text

            # Fallback to the tooltip text if no output is available yet.
            if not output_text:
                if item_row >= 0 and item_col >= 0:
                    item = self.table_widget.item(item_row, item_col)
                if item is not None:
                    try:
                        output_text = item.toolTip() or item.data(Qt.ItemDataRole.ToolTipRole) or ""
                    except RuntimeError:
                        return  # item's C++ object was deleted between retrieval and access

            if output_text:
                QGuiApplication.clipboard().setText(output_text)
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
        self._row_by_name.clear()

    def _get_or_create_item(self, row: int, col: int) -> QTableWidgetItem:
        item = self.table_widget.item(row, col)
        if item is None:
            item = _SortableItem()
            self.table_widget.setItem(row, col, item)
        return item

    def _on_header_double_clicked(self, col: int) -> None:
        if self._sort_column == col:
            self._sort_order = Qt.SortOrder.DescendingOrder if self._sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        else:
            self._sort_column = col
            self._sort_order = Qt.SortOrder.AscendingOrder
        self._apply_sort()

    def _apply_sort(self) -> None:
        if self._sort_column is None:
            return
        self.table_widget.sortItems(self._sort_column, self._sort_order)
        self.table_widget.horizontalHeader().setSortIndicator(self._sort_column, self._sort_order)
        self._rebuild_row_by_name()

    def _rebuild_row_by_name(self) -> None:
        self._row_by_name.clear()
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, Columns.NAME.value)
            if item is not None:
                name = item.data(Qt.ItemDataRole.UserRole)
                if name is not None:
                    self._row_by_name[name] = row

    @staticmethod
    def _set_text_if_changed(item: QTableWidgetItem, text: str) -> None:
        if item.text() != text:
            item.setText(text)

    @staticmethod
    def _set_tooltip_if_changed(item: QTableWidgetItem, tooltip: str) -> None:
        if item.toolTip() != tooltip:
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.ToolTipRole, tooltip)

    def update_tick(self, tick: TickData):
        """Refresh the table in place from pre-computed tick data.

        Rows persist across ticks and are keyed by test node_id via
        ``_row_by_name``. Only cells whose text or tooltip actually changed
        are rewritten; ``resizeColumnsToContents()`` runs only when new rows
        are appended. If the set of tests shrinks (e.g., after a reset) the
        table is fully rebuilt.
        """

        self._current_run_states = tick.run_states
        self._current_infos_by_name = tick.infos_by_name

        # If any previously-known test is no longer present, fall back to a rebuild.
        current_names = tick.infos_by_name.keys()
        if self._row_by_name and not self._row_by_name.keys() <= current_names:
            self.table_widget.setRowCount(0)
            self._row_by_name.clear()

        p_cores = get_performance_core_count()
        pref = get_pref()
        utilization_high_threshold = pref.utilization_high_threshold
        utilization_low_threshold = pref.utilization_low_threshold
        tooltip_line_limit = pref.tooltip_line_limit
        new_rows_added = False

        self.table_widget.setUpdatesEnabled(False)
        try:
            if self.table_widget.rowCount() < len(tick.infos_by_name):
                self.table_widget.setRowCount(len(tick.infos_by_name))

            for test_name, process_infos in tick.infos_by_name.items():
                row_number = self._row_by_name.get(test_name)
                if row_number is None:
                    row_number = len(self._row_by_name)
                    self._row_by_name[test_name] = row_number
                    new_rows_added = True

                pytest_run_state = tick.run_states[test_name]

                # NAME
                display_name = pytest_run_state.get_name()
                if test_name in tick.singleton_names:
                    display_name = f"{display_name} (singleton)"
                name_item = self._get_or_create_item(row_number, Columns.NAME.value)
                self._set_text_if_changed(name_item, display_name)
                if name_item.data(Qt.ItemDataRole.UserRole) != test_name:
                    name_item.setData(Qt.ItemDataRole.UserRole, test_name)

                # STATE
                state_item = self._get_or_create_item(row_number, Columns.STATE.value)
                self._set_text_if_changed(state_item, pytest_run_state.get_string())
                state_item.setForeground(pytest_run_state.get_qt_table_color())
                if pytest_run_state.get_state() == PytestRunnerState.RUNNING:
                    live_text = read_live_output(self._data_dir, test_name)
                    tooltip_text = tool_tip_limiter(live_text, line_limit=tooltip_line_limit) if live_text else ""
                elif len(process_infos) > 1 and process_infos[-1].output is not None:
                    tooltip_text = tool_tip_limiter(process_infos[-1].output, line_limit=tooltip_line_limit)
                else:
                    tooltip_text = ""
                self._set_tooltip_if_changed(state_item, tooltip_text)

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
                    elapsed_seconds = end_time - start_time
                    runtime_text = format_runtime(elapsed_seconds)
                else:
                    elapsed_seconds = None
                    runtime_text = ""

                # CPU and Memory
                if final_info is not None and final_info.cpu_percent is not None:
                    cpu_normalized = normalize_cpu_percent(final_info.cpu_percent, p_cores)
                    cpu_text = f"{cpu_normalized:.1f}%"
                else:
                    cpu_normalized = None
                    cpu_text = ""
                memory_text = f"{final_info.memory_percent:.2f}%" if (final_info is not None and final_info.memory_percent is not None) else ""

                cpu_item = self._get_or_create_item(row_number, Columns.CPU.value)
                self._set_text_if_changed(cpu_item, cpu_text)
                cpu_item.setData(_SORT_KEY_ROLE, cpu_normalized if cpu_normalized is not None else float("-inf"))
                if cpu_normalized is not None:
                    set_utilization_color(cpu_item, cpu_normalized / 100.0, utilization_high_threshold, utilization_low_threshold)
                else:
                    cpu_item.setForeground(QBrush())

                memory_item = self._get_or_create_item(row_number, Columns.MEMORY.value)
                self._set_text_if_changed(memory_item, memory_text)
                memory_value = final_info.memory_percent if (final_info is not None and final_info.memory_percent is not None) else None
                memory_item.setData(_SORT_KEY_ROLE, memory_value if memory_value is not None else float("-inf"))

                runtime_item = self._get_or_create_item(row_number, Columns.RUNTIME.value)
                self._set_text_if_changed(runtime_item, runtime_text)
                runtime_item.setData(_SORT_KEY_ROLE, elapsed_seconds if elapsed_seconds is not None else float("-inf"))

                # Per-test coverage
                coverage_pct = tick.per_test_coverage.get(test_name)
                coverage_text = f"{coverage_pct:.1%}" if coverage_pct is not None else ""
                coverage_item = self._get_or_create_item(row_number, Columns.COVERAGE.value)
                self._set_text_if_changed(coverage_item, coverage_text)
                coverage_item.setData(_SORT_KEY_ROLE, coverage_pct if coverage_pct is not None else float("-inf"))

                # Last pass data (persists across runs)
                last_pass = tick.last_pass_data.get(test_name)
                if last_pass is not None:
                    last_pass_start_ts, last_pass_duration = last_pass
                    last_pass_start_text = datetime.fromtimestamp(last_pass_start_ts).strftime("%Y-%m-%d %H:%M:%S")
                    last_pass_duration_text = format_runtime(last_pass_duration)
                else:
                    last_pass_start_ts = None
                    last_pass_duration = None
                    last_pass_start_text = ""
                    last_pass_duration_text = ""
                last_pass_start_item = self._get_or_create_item(row_number, Columns.LAST_PASS_START.value)
                self._set_text_if_changed(last_pass_start_item, last_pass_start_text)
                last_pass_start_item.setData(_SORT_KEY_ROLE, last_pass_start_ts if last_pass_start_ts is not None else float("-inf"))
                last_pass_duration_item = self._get_or_create_item(row_number, Columns.LAST_PASS_DURATION.value)
                self._set_text_if_changed(last_pass_duration_item, last_pass_duration_text)
                last_pass_duration_item.setData(_SORT_KEY_ROLE, last_pass_duration if last_pass_duration is not None else float("-inf"))

            if new_rows_added:
                self.table_widget.resizeColumnsToContents()

            if self._sort_column is not None:
                self.table_widget.sortItems(self._sort_column, self._sort_order)
                self.table_widget.horizontalHeader().setSortIndicator(self._sort_column, self._sort_order)
                self._rebuild_row_by_name()
        finally:
            self.table_widget.setUpdatesEnabled(True)
