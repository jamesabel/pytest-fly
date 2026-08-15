"""
Table tab — per-test status grid showing state, CPU, memory, runtime,
coverage, and last-pass information.
"""

import time
from datetime import datetime
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QGuiApplication
from PySide6.QtWidgets import QGroupBox, QMenu, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout
from typeguard import typechecked

from ...colors import TABLE_COLORS
from ...gui.gui_util import first_start_timestamp, format_commit, format_runtime, resolve_test_output, set_utilization_color, tool_tip_limiter
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
    COMMIT = 4
    RUNTIME = 5
    COVERAGE = 6
    LAST_PASS_START = 7
    LAST_PASS_DURATION = 8
    SPACER = 9  # empty trailing column that absorbs the stretch so real columns size to content


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

    @typechecked()
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
        self.table_widget.setHorizontalHeaderLabels(["Name", "State", "CPU", "Memory", "Commit", "Runtime", "Coverage", "Last Pass Start", "Last Pass Duration", ""])
        self.table_widget.horizontalHeader().setStretchLastSection(True)
        self.table_widget.horizontalHeader().setSortIndicatorShown(True)
        # Non-clickable sections still emit sectionDoubleClicked but no longer select the
        # whole column on (double-)click — the header is a sort control, not a selector.
        self.table_widget.horizontalHeader().setSectionsClickable(False)
        self.table_widget.horizontalHeader().sectionDoubleClicked.connect(self._on_header_double_clicked)
        # Double-click sorting is non-standard for Qt tables; say so where the user will hover.
        self.table_widget.horizontalHeader().setToolTip("Double-click a column header to sort; double-click again to reverse the order.")
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
            # Prefer the untruncated output from the latest PytestProcessInfo (falling
            # back to the live-log tail) so users get the full pytest output, not the
            # tooltip-limited view.
            output_text = ""
            if test_node_id is not None:
                output_text = resolve_test_output(self._current_infos_by_name.get(test_node_id, []), self._data_dir, test_node_id)

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
        """Copy the selected cell range to the clipboard as comma-separated rows."""
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
        """Return the item at (row, col), creating a :class:`_SortableItem` on first use."""
        item = self.table_widget.item(row, col)
        if item is None:
            item = _SortableItem()
            self.table_widget.setItem(row, col, item)
        return item

    def _update_cell(self, row: int, column: Columns, text: str, sort_key=None, *, sort_column: int | None) -> bool:
        """Write *text* and a numeric sort key into a cell; return ``True`` if the active sort went stale.

        ``None`` *sort_key* uses ``-inf`` so value-less cells sort last in ascending order.
        """
        item = self._get_or_create_item(row, column.value)
        self._set_text_if_changed(item, text)
        key = sort_key if sort_key is not None else float("-inf")
        return self._set_sort_key_if_changed(item, key) and sort_column == column.value

    def _on_header_double_clicked(self, col: int) -> None:
        """Sort by the double-clicked column, toggling direction on a repeat."""
        if self._sort_column == col:
            self._sort_order = Qt.SortOrder.DescendingOrder if self._sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        else:
            self._sort_column = col
            self._sort_order = Qt.SortOrder.AscendingOrder
        self._apply_sort()

    def _apply_sort(self) -> None:
        """Re-sort the table by the active column/direction and refresh the row index."""
        if self._sort_column is None:
            return
        self.table_widget.sortItems(self._sort_column, self._sort_order)
        self.table_widget.horizontalHeader().setSortIndicator(self._sort_column, self._sort_order)
        self._rebuild_row_by_name()

    def _rebuild_row_by_name(self) -> None:
        """Rebuild the test-name → row-index map after a sort reorders the rows."""
        self._row_by_name.clear()
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, Columns.NAME.value)
            if item is not None:
                name = item.data(Qt.ItemDataRole.UserRole)
                if name is not None:
                    self._row_by_name[name] = row

    @staticmethod
    def _set_text_if_changed(item: QTableWidgetItem, text: str) -> bool:
        """Set the item's text only when it changed; return ``True`` on change (avoids repaint churn)."""
        if item.text() != text:
            item.setText(text)
            return True
        return False

    @staticmethod
    def _set_sort_key_if_changed(item: QTableWidgetItem, value) -> bool:
        """Set the item's numeric sort key only when it changed; return ``True`` on change."""
        if item.data(_SORT_KEY_ROLE) != value:
            item.setData(_SORT_KEY_ROLE, value)
            return True
        return False

    @staticmethod
    def _set_tooltip_if_changed(item: QTableWidgetItem, tooltip: str) -> None:
        """Set the item's tooltip only when it changed (avoids repaint churn on each tick)."""
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
        sort_column = self._sort_column
        sort_dirty = False

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
                if self._set_text_if_changed(name_item, display_name) and sort_column == Columns.NAME.value:
                    sort_dirty = True
                if name_item.data(Qt.ItemDataRole.UserRole) != test_name:
                    name_item.setData(Qt.ItemDataRole.UserRole, test_name)

                # STATE
                state_item = self._get_or_create_item(row_number, Columns.STATE.value)
                if self._set_text_if_changed(state_item, pytest_run_state.get_string()) and sort_column == Columns.STATE.value:
                    sort_dirty = True
                state_item.setForeground(TABLE_COLORS[pytest_run_state.get_state()])
                if pytest_run_state.get_state() == PytestRunnerState.RUNNING:
                    live_text = read_live_output(self._data_dir, test_name)
                    tooltip_text = tool_tip_limiter(live_text, line_limit=tooltip_line_limit) if live_text else ""
                elif len(process_infos) > 1 and process_infos[-1].output is not None:
                    tooltip_text = tool_tip_limiter(process_infos[-1].output, line_limit=tooltip_line_limit)
                else:
                    tooltip_text = ""
                self._set_tooltip_if_changed(state_item, tooltip_text)

                # Find the timestamp when the test started running and the final completed entry
                start_time = first_start_timestamp(process_infos)
                final_info = None
                for info in process_infos:
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

                sort_dirty |= self._update_cell(row_number, Columns.CPU, cpu_text, cpu_normalized, sort_column=sort_column)
                cpu_item = self._get_or_create_item(row_number, Columns.CPU.value)
                if cpu_normalized is not None:
                    set_utilization_color(cpu_item, cpu_normalized / 100.0, utilization_high_threshold, utilization_low_threshold)
                else:
                    cpu_item.setForeground(QBrush())

                memory_value = final_info.memory_percent if (final_info is not None and final_info.memory_percent is not None) else None
                sort_dirty |= self._update_cell(row_number, Columns.MEMORY, memory_text, memory_value, sort_column=sort_column)

                # Commit charge (peak commit size of the test's process subtree)
                commit_value = final_info.commit_bytes if (final_info is not None and final_info.commit_bytes is not None) else None
                sort_dirty |= self._update_cell(row_number, Columns.COMMIT, format_commit(commit_value), commit_value, sort_column=sort_column)

                sort_dirty |= self._update_cell(row_number, Columns.RUNTIME, runtime_text, elapsed_seconds, sort_column=sort_column)

                # Per-test coverage
                coverage_pct = tick.per_test_coverage.get(test_name)
                coverage_text = f"{coverage_pct:.1%}" if coverage_pct is not None else ""
                sort_dirty |= self._update_cell(row_number, Columns.COVERAGE, coverage_text, coverage_pct, sort_column=sort_column)

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
                sort_dirty |= self._update_cell(row_number, Columns.LAST_PASS_START, last_pass_start_text, last_pass_start_ts, sort_column=sort_column)
                sort_dirty |= self._update_cell(row_number, Columns.LAST_PASS_DURATION, last_pass_duration_text, last_pass_duration, sort_column=sort_column)

            if new_rows_added:
                self.table_widget.resizeColumnsToContents()

            if sort_column is not None and (new_rows_added or sort_dirty):
                self.table_widget.sortItems(sort_column, self._sort_order)
                self.table_widget.horizontalHeader().setSortIndicator(sort_column, self._sort_order)
                self._rebuild_row_by_name()
        finally:
            self.table_widget.setUpdatesEnabled(True)
