"""
History tab — summaries of recent test runs.

Shows one row per run (start time, duration, completion status, pass/fail statistics, and
the program-under-test version), with the run's failed tests as expandable child rows.
Rows can be multi-selected and copied to the clipboard (Ctrl+C or right-click → Copy).
The number of runs shown is the Configuration tab's "History Run Limit" preference.
"""

from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QGroupBox, QMenu, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from ...colors import TABLE_COLORS
from ...db import PytestProcessInfoReader
from ...interfaces import PytestRunnerState
from ...preferences import get_pref
from ...run_history import RunHistorySummary, build_run_history
from ..gui_util import format_runtime

_COLUMNS = ("Start", "Duration", "Status", "Pass", "Fail", "Other", "Total", "Version")
_START_COLUMN, _DURATION_COLUMN, _STATUS_COLUMN, _PASS_COLUMN, _FAIL_COLUMN, _OTHER_COLUMN, _TOTAL_COLUMN, _VERSION_COLUMN = range(len(_COLUMNS))

# Run GUID stored on each top-level item so expansion and selection state survive rebuilds.
_RUN_GUID_ROLE = Qt.ItemDataRole.UserRole


class HistoryTab(QGroupBox):
    """Tab displaying per-run summaries of recent test runs, most recent first."""

    def __init__(self):
        super().__init__()
        self.setTitle("Run History (most recent first)")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(list(_COLUMNS))
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setToolTip(
            "One row per recent test run; expand a run to see its failed tests.\n"
            "Other = terminated, stopped, or still queued/running tests.\n"
            "Select rows (Ctrl/Shift-click for several) and copy them with Ctrl+C or right-click → Copy.\n"
            "The number of runs shown is set by the Configuration tab's History Run Limit."
        )
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree)

        # WidgetWithChildrenShortcut: the tree's viewport has focus during interaction, so a
        # plain widget-context shortcut on the tree itself would never fire.
        copy_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self._tree)
        copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_shortcut.activated.connect(self.copy_selection_to_clipboard)

        # Change-detection state: rebuild only when the DB content or the run limit changed.
        self._change_token: tuple[int, int] | None = None
        self._run_limit: int | None = None

    def update_tick(self, db: PytestProcessInfoReader) -> None:
        """Refresh the run summaries from the DB; a no-op when nothing changed since the last tick."""
        run_limit = max(get_pref().history_run_limit, 1)
        change_token = db.query_change_token()
        if change_token == self._change_token and run_limit == self._run_limit:
            return
        self._change_token = change_token
        self._run_limit = run_limit
        self._rebuild(build_run_history(db.query_recent_runs(run_limit)))

    def selection_as_text(self) -> str:
        """Return the highlighted rows as clipboard text, in visual (tree) order.

        A run row becomes one tab-separated line of its column values; a failed-test row
        becomes the test's node_id.  Empty when nothing is selected.
        """
        lines: list[str] = []
        for index in range(self._tree.topLevelItemCount()):
            run_item = self._tree.topLevelItem(index)
            if run_item is None:
                continue
            if run_item.isSelected():
                lines.append("\t".join(run_item.text(column) for column in range(len(_COLUMNS))))
            for child_index in range(run_item.childCount()):
                child = run_item.child(child_index)
                if child is not None and child.isSelected():
                    lines.append(child.text(0))
        return "\n".join(lines)

    def copy_selection_to_clipboard(self) -> None:
        """Copy the highlighted rows to the system clipboard; a no-op when nothing is selected."""
        text = self.selection_as_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def _show_context_menu(self, position: QPoint) -> None:
        """Right-click menu: Copy the highlighted rows to the clipboard."""
        menu = QMenu(self._tree)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(bool(self._tree.selectedItems()))
        selected_action = menu.exec_(self._tree.viewport().mapToGlobal(position))
        if selected_action == copy_action:
            self.copy_selection_to_clipboard()

    def _rebuild(self, summaries: list[RunHistorySummary]) -> None:
        """Repopulate the tree, preserving each still-present run's expansion and selection state."""
        expansion_by_guid: dict[str, bool] = {}
        selected_run_guids: set[str] = set()
        selected_failed_tests: set[tuple[str, str]] = set()  # (run_guid, test node_id)
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            if item is None:
                continue
            run_guid = item.data(0, _RUN_GUID_ROLE)
            # Only a row with failed-test children has a meaningful expansion state to keep.
            # Recording childless rows would freeze an in-progress run in its initial collapsed
            # state and defeat the auto-expand when its first failure appears.
            if item.childCount() > 0:
                expansion_by_guid[run_guid] = item.isExpanded()
            if item.isSelected():
                selected_run_guids.add(run_guid)
            for child_index in range(item.childCount()):
                child = item.child(child_index)
                if child is not None and child.isSelected():
                    selected_failed_tests.add((run_guid, child.text(0)))

        self._tree.clear()
        fail_color = TABLE_COLORS[PytestRunnerState.FAIL]
        pass_color = TABLE_COLORS[PytestRunnerState.PASS]
        for summary in summaries:
            texts = [""] * len(_COLUMNS)
            texts[_START_COLUMN] = datetime.fromtimestamp(summary.start_ts).strftime("%Y-%m-%d %H:%M:%S")
            texts[_DURATION_COLUMN] = format_runtime(summary.duration)
            texts[_STATUS_COLUMN] = "Complete" if summary.is_complete else "In progress"
            texts[_PASS_COLUMN] = str(summary.n_pass)
            texts[_FAIL_COLUMN] = str(summary.n_fail)
            texts[_OTHER_COLUMN] = str(summary.n_other)
            texts[_TOTAL_COLUMN] = str(summary.n_total)
            texts[_VERSION_COLUMN] = summary.put_version
            run_item = QTreeWidgetItem(texts)
            run_item.setData(0, _RUN_GUID_ROLE, summary.run_guid)
            if summary.n_pass > 0:
                run_item.setForeground(_PASS_COLUMN, pass_color)
            if summary.n_fail > 0:
                run_item.setForeground(_FAIL_COLUMN, fail_color)
            for failed_test in summary.failed_tests:
                failed_item = QTreeWidgetItem([failed_test])
                failed_item.setForeground(0, fail_color)
                run_item.addChild(failed_item)
            self._tree.addTopLevelItem(run_item)
            # Selection (like the column span below) only takes effect once the item is in the tree.
            run_item.setSelected(summary.run_guid in selected_run_guids)
            # Runs with failures start expanded so the failed tests are immediately visible;
            # a run the user explicitly collapsed (or expanded) stays that way across rebuilds.
            run_item.setExpanded(expansion_by_guid.get(summary.run_guid, summary.n_fail > 0))
            for child_index in range(run_item.childCount()):
                child = run_item.child(child_index)
                if child is not None:
                    child.setSelected((summary.run_guid, child.text(0)) in selected_failed_tests)
                    # A failed-test child row is a single name, not tabular data — span it across all columns.
                    child.setFirstColumnSpanned(True)

        for column in range(len(_COLUMNS)):
            self._tree.resizeColumnToContents(column)
