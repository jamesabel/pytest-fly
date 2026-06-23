"""
Configuration tab — exposes user-editable preferences such as verbosity,
parallelism, refresh rate, and utilization thresholds.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from tobool import to_bool_strict

from pytest_fly.gui.about_tab.project_info import get_project_info
from pytest_fly.gui.gui_util import get_text_dimensions
from pytest_fly.interfaces import OrderingAspect, RunMode
from pytest_fly.logger import get_logger
from pytest_fly.paths import get_default_data_dir
from pytest_fly.platform.platform_info import get_performance_core_count
from pytest_fly.preferences import (
    TIME_UNITS,
    chart_window_minutes_default,
    commit_gate_threshold_default,
    commit_warning_threshold_default,
    cpu_active_epsilon_default,
    duration_to_seconds,
    get_active_put_path,
    get_ordering_aspects_ordered,
    get_pref,
    graph_font_size_default,
    max_descendant_processes_default,
    refresh_rate_default,
    set_active_put_path,
    set_ordering_aspects_ordered,
    stall_kill_value_default,
    stall_warn_value_default,
    tooltip_line_limit_default,
    utilization_high_threshold_default,
    utilization_low_threshold_default,
)

_ordering_aspect_labels: dict[OrderingAspect, str] = {
    OrderingAspect.FAILED_FIRST: "Failed tests",
    OrderingAspect.NEVER_RUN_FIRST: "Never-run tests",
    OrderingAspect.LONGEST_PRIOR_FIRST: "Longest prior execution time",
    OrderingAspect.COVERAGE_EFFICIENCY: "Coverage efficiency (lines/sec)",
}

_ordering_aspect_tooltips: dict[OrderingAspect, str] = {
    OrderingAspect.FAILED_FIRST: "Tests that failed in the previous run run first. Tests with no prior record tie for last.",
    OrderingAspect.NEVER_RUN_FIRST: "Tests with no record in the database (any program-under-test version) run first.",
    OrderingAspect.LONGEST_PRIOR_FIRST: (
        "Tests with the longest prior passing-run duration run first. Helps parallel runs by starting the\n"
        "critical-path tests earliest; shorter tests backfill the remaining workers. Tests with no prior\n"
        "duration tie for last."
    ),
    OrderingAspect.COVERAGE_EFFICIENCY: "Tests with the highest lines-covered-per-second run first. Requires prior duration and coverage data; tests missing either tie for last.",
}


class OrderingAspectsWidget(QGroupBox):
    """Reorderable, per-row-checkable list of test-ordering aspects."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Test Ordering (highest priority=top)", parent)
        # Hug our content — do not stretch into parent layout whitespace.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip(
            "Controls the order tests run in.\n\n"
            "Check a row to enable that aspect; uncheck to disable. Enabled rows appear above disabled ones.\n"
            "Position sets priority — the topmost enabled row is the primary sort; rows below it break ties.\n"
            "Use Up / Down to reorder the selected row.\n\n"
            "Failed tests: previously-failed tests run before previously-passed ones.\n"
            "Never-run tests: tests with no record in the database run before tests that have run before.\n"
            "Longest prior execution time: slowest passing tests run first — helps parallel runs by starting\n"
            "the critical path earliest so short tests backfill the remaining workers.\n"
            "Coverage efficiency: tests with the highest lines-covered-per-second run first.\n\n"
            "All aspects apply in every run mode, including Restart — prior-run data shapes execution order,\n"
            "not which tests run. Tests missing the data an aspect needs tie for last under that aspect.\n"
            "Singleton tests always run last regardless of these settings."
        )

        outer = QVBoxLayout()
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)
        outer.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setLayout(outer)

        body = QHBoxLayout()
        body.setSpacing(4)
        body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        outer.addLayout(body)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # Remove the scroll bars — with only four fixed rows the widget is sized
        # to show them all, so scrolling would be misleading whitespace.
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.addWidget(self._list)

        buttons = QVBoxLayout()
        buttons.setAlignment(Qt.AlignmentFlag.AlignTop)
        buttons.setSpacing(2)
        self._up_button = QPushButton("Up")
        self._up_button.clicked.connect(lambda: self._move_selected(-1))
        buttons.addWidget(self._up_button)
        self._down_button = QPushButton("Down")
        self._down_button.clicked.connect(lambda: self._move_selected(1))
        buttons.addWidget(self._down_button)
        body.addLayout(buttons)

        self._populate_from_prefs()
        self._resize_list_to_content()
        # Connect after populating so setCheckState during populate does not
        # fire the persistence slot.
        self._list.itemChanged.connect(self._on_item_changed)

    def _resize_list_to_content(self) -> None:
        """Fix the list widget's size to exactly fit its rows and longest label.

        Sized from the actual rendered text bounding box (not just glyph
        advance) plus the space the style needs for the check indicator and
        item margins.  The components are deliberately over-measured: Qt's
        reported ``PM_IndicatorWidth`` under-counts on Windows (returns ~14 px
        for a visibly ~20 px box) and ``horizontalAdvance`` under-counts when
        ClearType widens glyphs.  The goal is a list that's just wider than
        needed — never narrower.
        """
        count = self._list.count()
        if count == 0:
            return
        fm = self._list.fontMetrics()
        # Take the larger of horizontalAdvance and boundingRect — the latter
        # wins for glyphs that extend past their advance (italic f, descenders).
        text_width = max(max(fm.horizontalAdvance(_ordering_aspect_labels[a]), fm.boundingRect(_ordering_aspect_labels[a]).width()) for a in _ordering_aspect_labels)
        # Style-reported components:
        style = self._list.style()
        indicator = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, self._list)
        # PM_ScrollBarExtent: even though the scroll bars are turned off, some
        # item-view metrics reserve the extent in their layout calculations.
        scroll_extent = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, self._list)
        frame = 2 * self._list.frameWidth()
        # Fixed slack: left/right item margins, indicator-to-text gap, plus
        # general safety.  Kept generous because ClearType/DirectWrite render
        # text a few percent wider than ``QFontMetrics.horizontalAdvance``
        # predicts, and hi-DPI scaling amplifies the shortfall.
        slack = 80
        width = text_width + indicator + scroll_extent + slack + frame
        row_height = self._list.sizeHintForRow(0) or fm.height() + 4
        self._list.setFixedSize(width, row_height * count + frame)

    def _populate_from_prefs(self) -> None:
        """Render enabled aspects (in priority order) first, then disabled aspects in enum order."""
        self._list.clear()
        enabled = get_ordering_aspects_ordered()
        disabled = [a for a in OrderingAspect if a not in enabled]
        for aspect in list(enabled) + disabled:
            item = QListWidgetItem(_ordering_aspect_labels[aspect])
            item.setToolTip(_ordering_aspect_tooltips[aspect])
            item.setData(Qt.ItemDataRole.UserRole, aspect.value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if aspect in enabled else Qt.CheckState.Unchecked)
            self._list.addItem(item)

    def _move_selected(self, delta: int) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(new_row, item)
        self._list.setCurrentRow(new_row)
        self._persist()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Keep enabled rows above disabled rows when the user toggles a checkbox.

        Unchecking a row drops it to the bottom of the list; checking a row
        promotes it to the end of the enabled group (just above the first
        disabled row).  Always persists.
        """
        current = self._list.row(item)
        if item.checkState() == Qt.CheckState.Checked:
            # Target row: first unchecked row above the current position,
            # i.e. the insertion point at the end of the enabled group.
            target = current
            for i in range(current):
                if self._list.item(i).checkState() != Qt.CheckState.Checked:
                    target = i
                    break
            else:
                target = current  # already at/after the last checked row
        else:
            target = self._list.count() - 1  # move to the very end

        if target != current:
            # Signals block prevents _on_item_changed from re-entering while
            # the row is moved programmatically.
            self._list.blockSignals(True)
            taken = self._list.takeItem(current)
            self._list.insertItem(target, taken)
            self._list.setCurrentRow(target)
            self._list.blockSignals(False)

        self._persist()

    def _persist(self) -> None:
        enabled: list[OrderingAspect] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                try:
                    enabled.append(OrderingAspect(item.data(Qt.ItemDataRole.UserRole)))
                except ValueError:
                    continue
        set_ordering_aspects_ordered(enabled)


log = get_logger()

minimum_refresh_rate = 1.0
minimum_tooltip_line_limit = 1
minimum_chart_window_minutes = 0.5
minimum_graph_font_size = 6


def _add_labeled_lineedit(
    layout: QVBoxLayout,
    label_text: str,
    initial_value: str,
    validator: QValidator,
    on_changed: Callable[[str], None],
    char_width: int = 4,
    tooltip: str = "",
) -> QLineEdit:
    """Create a labelled :class:`QLineEdit` with a validator and add it to *layout*.

    Eliminates the repeated label + line-edit + validator + connect pattern
    used for each numeric preference field.

    :param layout: Parent layout to append widgets to.
    :param label_text: Descriptive label shown above the input.
    :param initial_value: Text to pre-fill.
    :param validator: Input validator (e.g. ``QIntValidator``).
    :param on_changed: Slot connected to ``textChanged``.
    :param char_width: Number of monospace characters used to size the field.
    :param tooltip: Optional hover text applied to both the label and the input.
    :return: The created :class:`QLineEdit`.
    """
    label = QLabel(label_text)
    lineedit = QLineEdit()
    lineedit.setText(initial_value)
    lineedit.setValidator(validator)
    lineedit.setFixedWidth(get_text_dimensions(char_width * "X", True).width())
    lineedit.textChanged.connect(on_changed)
    if tooltip:
        label.setToolTip(tooltip)
        lineedit.setToolTip(tooltip)
    layout.addWidget(label)
    layout.addWidget(lineedit)
    return lineedit


def _format_number(value: float) -> str:
    """Render a number without a trailing ``.0`` (so ``10.0`` shows as ``10``)."""
    return str(int(value)) if float(value).is_integer() else str(value)


def _add_labeled_duration(
    layout: QVBoxLayout,
    label_text: str,
    value: float,
    unit: str,
    on_changed: Callable[..., None],
    char_width: int = 5,
    tooltip: str = "",
) -> tuple[QLineEdit, QComboBox]:
    """Create a labelled value line-edit plus a Seconds/Minutes/Hours unit selector.

    Lets a timeout be entered in whichever unit reads best; both widgets call *on_changed*
    (which should read both and persist). Returns the ``(lineedit, combobox)`` pair.

    :param tooltip: Optional hover text applied to the label, value field, and unit selector.
    """
    label = QLabel(label_text)
    row = QHBoxLayout()
    row.setAlignment(Qt.AlignmentFlag.AlignLeft)
    lineedit = QLineEdit()
    lineedit.setText(_format_number(value))
    lineedit.setValidator(QDoubleValidator())
    lineedit.setFixedWidth(get_text_dimensions(char_width * "X", True).width())
    lineedit.textChanged.connect(on_changed)
    row.addWidget(lineedit)
    combo = QComboBox()
    combo.addItems(TIME_UNITS)
    combo.setCurrentText(unit if unit in TIME_UNITS else TIME_UNITS[0])
    combo.currentTextChanged.connect(on_changed)
    row.addWidget(combo)
    if tooltip:
        label.setToolTip(tooltip)
        lineedit.setToolTip(tooltip)
        combo.setToolTip(tooltip)
    layout.addWidget(label)
    layout.addLayout(row)
    return lineedit, combo


class Configuration(QWidget):
    """Configuration tab exposing user-editable preferences (verbose, processes, refresh rate, thresholds)."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Configuration")

        # Wrap the content in a scroll area so the (now fairly tall) set of options never
        # forces the main window's minimum height past the screen — the tab scrolls instead.
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer_layout)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        outer_layout.addWidget(scroll_area)

        content = QWidget()
        scroll_area.setWidget(content)

        # Two columns: general options on the left, the (tall) Liveness / Recovery group on the
        # right. Horizontal room is plentiful; vertical is not, so spread out sideways.
        columns_layout = QHBoxLayout()
        columns_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        content.setLayout(columns_layout)

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        columns_layout.addLayout(layout)

        right_column = QVBoxLayout()
        right_column.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        columns_layout.addLayout(right_column)

        pref = get_pref()

        # One-time reconciliation: existing users with run_mode == RESUME should see
        # the new "Resume Without Program Check" box already checked so the UI
        # reflects their persisted behavior.
        if pref.run_mode == RunMode.RESUME and not pref.resume_skip_put_check:
            pref.resume_skip_put_check = True

        # Resume-mode behavior option
        self.resume_skip_put_check_checkbox = QCheckBox("Resume Without Program Check (default: off)")
        self.resume_skip_put_check_checkbox.setToolTip(
            "When unchecked, pytest-fly checks the program under test (PUT) for modifications\n"
            "and runs a full Restart if the PUT has changed.\n"
            "When checked, pytest-fly forces a Resume even if the PUT has changed."
        )
        self.resume_skip_put_check_checkbox.setChecked(to_bool_strict(pref.resume_skip_put_check))
        self.resume_skip_put_check_checkbox.stateChanged.connect(self.update_resume_skip_put_check)
        layout.addWidget(self.resume_skip_put_check_checkbox)

        layout.addWidget(QLabel(""))  # space

        self.ordering_aspects_widget = OrderingAspectsWidget(self)
        layout.addWidget(self.ordering_aspects_widget)

        layout.addWidget(QLabel(""))  # space

        # Numeric preference fields — use the shared helper to avoid repetition.
        self.processes_lineedit = _add_labeled_lineedit(layout, f"Processes (recommended: {get_performance_core_count()})", str(pref.processes), QIntValidator(), self.update_processes)

        layout.addWidget(QLabel(""))  # space

        self.refresh_rate_lineedit = _add_labeled_lineedit(
            layout, f"Refresh Rate (seconds, {minimum_refresh_rate} minimum, {refresh_rate_default} default)", str(pref.refresh_rate), QDoubleValidator(), self.update_refresh_rate
        )

        layout.addWidget(QLabel(""))  # space

        high_label = f"High Utilization Threshold (0.0-1.0, {utilization_high_threshold_default} default)"
        self.utilization_high_threshold_lineedit = _add_labeled_lineedit(layout, high_label, str(pref.utilization_high_threshold), QDoubleValidator(), self.update_utilization_high_threshold)

        low_label = f"Low Utilization Threshold (0.0-1.0, {utilization_low_threshold_default} default)"
        self.utilization_low_threshold_lineedit = _add_labeled_lineedit(layout, low_label, str(pref.utilization_low_threshold), QDoubleValidator(), self.update_utilization_low_threshold)

        layout.addWidget(QLabel(""))  # space

        commit_label = f"Commit Charge Warning Threshold (0.0-1.0, {commit_warning_threshold_default} default)"
        self.commit_warning_threshold_lineedit = _add_labeled_lineedit(layout, commit_label, str(pref.commit_warning_threshold), QDoubleValidator(), self.update_commit_warning_threshold)

        layout.addWidget(QLabel(""))  # space

        tooltip_label = f"Tooltip Line Limit (min {minimum_tooltip_line_limit}, {tooltip_line_limit_default} default)"
        self.tooltip_line_limit_lineedit = _add_labeled_lineedit(layout, tooltip_label, str(pref.tooltip_line_limit), QIntValidator(), self.update_tooltip_line_limit, char_width=6)

        layout.addWidget(QLabel(""))  # space

        chart_window_label = f"System Metrics Chart Window (minutes, {minimum_chart_window_minutes} minimum, {chart_window_minutes_default} default)"
        self.chart_window_minutes_lineedit = _add_labeled_lineedit(
            layout, chart_window_label, str(pref.chart_window_minutes), QDoubleValidator(), self.update_chart_window_minutes, char_width=6
        )

        layout.addWidget(QLabel(""))  # space

        graph_font_size_label = f"Progress Graph Font Size (points, {minimum_graph_font_size} minimum, {graph_font_size_default} default)"
        self.graph_font_size_lineedit = _add_labeled_lineedit(layout, graph_font_size_label, str(pref.graph_font_size), QIntValidator(), self.update_graph_font_size, char_width=6)

        layout.addWidget(QLabel(""))  # space

        # Target project path (PUT). Stored as a preference (independent of where pytest-fly keeps
        # its own data), so it is freely editable here and takes effect on the next test run.
        self._active_put_path = str(get_active_put_path())
        layout.addWidget(QLabel("Target Project Path (program under test)"))
        target_path_row = QHBoxLayout()
        self.target_project_path_lineedit = QLineEdit()
        self.target_project_path_lineedit.setText(self._active_put_path)
        self.target_project_path_lineedit.setToolTip(
            "Tests are collected recursively from this path. To run only a subset (e.g. just your\n"
            "'tests' directory), point this at that subdirectory.\n\n"
            "Note: pytest's testpaths setting is not used — pytest-fly passes this path to pytest\n"
            "explicitly, which overrides testpaths."
        )
        self.target_project_path_lineedit.editingFinished.connect(self._commit_target_project_path)
        target_path_row.addWidget(self.target_project_path_lineedit)
        self.target_project_path_browse = QPushButton("Browse…")
        self.target_project_path_browse.clicked.connect(self._browse_target_project_path)
        target_path_row.addWidget(self.target_project_path_browse)
        layout.addLayout(target_path_row)
        target_path_hint = QLabel("The project whose tests are run. Applies on the next run; empty resolves to the launch directory.")
        target_path_hint.setStyleSheet("color: gray;")
        layout.addWidget(target_path_hint)

        layout.addWidget(QLabel(""))  # space

        # Test results DB directory — empty means use the workspace-local default (<workspace>/.pytest-fly/).
        default_results_dir = str(get_default_data_dir())
        layout.addWidget(QLabel(f"Test Results DB Directory (empty = default: {default_results_dir})"))
        results_dir_row = QHBoxLayout()
        self.test_results_db_dir_lineedit = QLineEdit()
        self.test_results_db_dir_lineedit.setText(pref.test_results_db_dir)
        self.test_results_db_dir_lineedit.setPlaceholderText(default_results_dir)
        self.test_results_db_dir_lineedit.textChanged.connect(self.update_test_results_db_dir)
        results_dir_row.addWidget(self.test_results_db_dir_lineedit)
        self.test_results_db_dir_browse = QPushButton("Browse…")
        self.test_results_db_dir_browse.clicked.connect(self._browse_test_results_db_dir)
        results_dir_row.addWidget(self.test_results_db_dir_browse)
        layout.addLayout(results_dir_row)

        # Liveness / recovery group — stall watchdog and admission gates. Lives in the right
        # column (see the two-column content layout above) so the tall set of options uses the
        # available horizontal room instead of overflowing vertically.
        # See docs/pytest-fly-liveness-recovery-spec.md.
        liveness_group = QGroupBox("Liveness / Recovery")
        liveness_group.setToolTip(
            "Detect and recover from wedged runs, and throttle runaway process spawning.\n"
            "The stall watchdog is advisory only (a banner); it never kills a test on its own\n"
            "unless automatic escalation is explicitly enabled. The admission gates are off by\n"
            "default and only defer dispatching new tests — they never cap how long a test runs."
        )
        liveness_layout = QVBoxLayout()
        liveness_group.setLayout(liveness_layout)

        self.stall_detection_enabled_checkbox = QCheckBox("Stall Detection (advisory banner, default: on)")
        self.stall_detection_enabled_checkbox.setToolTip(
            "Watches for a wedged run — a hung test whose nested process tree has deadlocked, which\n"
            "would otherwise keep pytest-fly reporting 'running' forever and never re-enable Run.\n\n"
            "Flags the run as stalled (a banner only — nothing is killed) when, for the whole Stall\n"
            "Warn Window, no test starts or finishes AND no in-flight test uses any CPU. A test that\n"
            "is genuinely working keeps using CPU and never trips this, no matter how long it runs.\n\n"
            "When stalled, click Force Stop to recover: in-flight processes are killed, leftover tests\n"
            "are marked stopped, and Run re-enables — without killing pytest-fly from the OS."
        )
        self.stall_detection_enabled_checkbox.setChecked(to_bool_strict(pref.stall_detection_enabled))
        self.stall_detection_enabled_checkbox.stateChanged.connect(self.update_stall_detection_enabled)
        liveness_layout.addWidget(self.stall_detection_enabled_checkbox)

        self.stall_warn_value_lineedit, self.stall_warn_unit_combo = _add_labeled_duration(
            liveness_layout,
            f"Stall Warn Window (default: {_format_number(stall_warn_value_default)} minutes)",
            pref.stall_warn_value,
            pref.stall_warn_unit,
            self.update_stall_warn,
            tooltip=(
                "How long the run must show no progress and no CPU activity before the stall banner\n"
                "appears. This is a run-wide signal, not a per-test timeout: a long but active test\n"
                "never triggers it. Enter the duration in seconds, minutes, or hours."
            ),
        )

        self.cpu_active_epsilon_lineedit = _add_labeled_lineedit(
            liveness_layout,
            f"CPU Idle Epsilon (percent, {cpu_active_epsilon_default} default)",
            str(pref.cpu_active_epsilon),
            QDoubleValidator(),
            self.update_cpu_active_epsilon,
            char_width=6,
            tooltip=(
                "The CPU level (percent of one core) below which an in-flight test counts as 'idle'\n"
                "for stall detection. A deadlocked process tree sits near 0%; a working test stays\n"
                "above this and keeps resetting the stall timer. ~1% is a good default.\n\n"
                "Note: a test blocked on slow network or disk I/O also looks idle — which is why\n"
                "stall detection only warns by default rather than killing anything."
            ),
        )

        self.auto_force_stop_on_stall_checkbox = QCheckBox("Auto Force-stop & Reset on Stall (default: off)")
        self.auto_force_stop_on_stall_checkbox.setToolTip(
            "When OFF (default), a stall only shows a banner — you click Force Stop to recover.\n\n"
            "When ON, after the Stall Kill Window of continuous stalling the run is automatically\n"
            "force-stopped and reset (useful for unattended CI). Leave OFF if your tests can\n"
            "legitimately block on slow network/disk I/O, since that also reads as idle and could\n"
            "trigger a false recovery."
        )
        self.auto_force_stop_on_stall_checkbox.setChecked(to_bool_strict(pref.auto_force_stop_on_stall))
        self.auto_force_stop_on_stall_checkbox.stateChanged.connect(self.update_auto_force_stop_on_stall)
        liveness_layout.addWidget(self.auto_force_stop_on_stall_checkbox)

        self.stall_kill_value_lineedit, self.stall_kill_unit_combo = _add_labeled_duration(
            liveness_layout,
            f"Stall Kill Window (must exceed the warn window; default: {_format_number(stall_kill_value_default)} minutes)",
            pref.stall_kill_value,
            pref.stall_kill_unit,
            self.update_stall_kill,
            tooltip=(
                "Only used when 'Auto Force-stop & Reset on Stall' is enabled. How long the run must\n"
                "stay continuously stalled before it is automatically force-stopped and reset.\n\n"
                "Must be longer than the Stall Warn Window, or automatic escalation is disabled.\n"
                "Enter the duration in seconds, minutes, or hours."
            ),
        )

        self.process_count_gate_enabled_checkbox = QCheckBox("Process-count Admission Gate (default: off)")
        self.process_count_gate_enabled_checkbox.setToolTip(
            "Throttles runaway process spawning. Before starting another test, pytest-fly waits while\n"
            "the total number of processes in its tree — every test process plus anything those tests\n"
            "spawn (subprocesses, multiprocessing pools) — is at or above 'Max Descendant Processes'.\n\n"
            "Only defers starting new tests; it never caps how long a running test takes, and at least\n"
            "one test always runs so the suite can't deadlock behind the gate. Off by default."
        )
        self.process_count_gate_enabled_checkbox.setChecked(to_bool_strict(pref.process_count_gate_enabled))
        self.process_count_gate_enabled_checkbox.stateChanged.connect(self.update_process_count_gate_enabled)
        liveness_layout.addWidget(self.process_count_gate_enabled_checkbox)

        self.max_descendant_processes_lineedit = _add_labeled_lineedit(
            liveness_layout,
            f"Max Descendant Processes ({max_descendant_processes_default} default)",
            str(pref.max_descendant_processes),
            QIntValidator(),
            self.update_max_descendant_processes,
            char_width=7,
            tooltip=(
                "The ceiling for the process-count admission gate: pytest-fly defers starting new tests\n"
                "while its whole process tree is at or above this many processes.\n\n"
                "Counts grandchildren that tests spawn themselves, not just the test workers. The\n"
                "default scales with your CPU core count."
            ),
        )

        self.commit_gate_enabled_checkbox = QCheckBox("Commit-charge Admission Gate (default: off)")
        self.commit_gate_enabled_checkbox.setToolTip(
            "Throttles dispatch by memory commitment rather than process count. Before starting another\n"
            "test, pytest-fly waits while system commit charge (RAM + page file currently committed)\n"
            "exceeds the threshold below.\n\n"
            "Complements the process-count gate; when both are on, both must allow a test before it\n"
            "starts. Only defers new tests, and at least one always runs. Off by default. (Commit\n"
            "charge is read on Windows; on other platforms this gate stays out of the way.)"
        )
        self.commit_gate_enabled_checkbox.setChecked(to_bool_strict(pref.commit_gate_enabled))
        self.commit_gate_enabled_checkbox.stateChanged.connect(self.update_commit_gate_enabled)
        liveness_layout.addWidget(self.commit_gate_enabled_checkbox)

        self.commit_gate_threshold_lineedit = _add_labeled_lineedit(
            liveness_layout,
            f"Commit Gate Threshold (0.0-1.0, {commit_gate_threshold_default} default)",
            str(pref.commit_gate_threshold),
            QDoubleValidator(),
            self.update_commit_gate_threshold,
            tooltip=(
                "The fraction of the system commit limit (0.0–1.0) at or above which the commit-charge\n"
                "gate defers starting new tests. For example, 0.90 means 'hold off once commit charge\n"
                "reaches 90% of the limit.' Only used when the Commit-charge Admission Gate is enabled."
            ),
        )

        right_column.addWidget(liveness_group)
        right_column.addStretch()

        layout.addWidget(QLabel(""))  # space

        # Expert group — settings most users should not need to change. Placed last to de-emphasize.
        expert_group = QGroupBox("Expert")
        expert_group.setToolTip("Advanced diagnostic options. Normal users should not need to change these.")
        expert_layout = QVBoxLayout()
        expert_group.setLayout(expert_layout)

        self.verbose_checkbox = QCheckBox("Verbose (default: off)")
        self.verbose_checkbox.setChecked(to_bool_strict(pref.verbose))
        self.verbose_checkbox.stateChanged.connect(self.update_verbose)
        expert_layout.addWidget(self.verbose_checkbox)

        self.perf_logging_checkbox = QCheckBox(f"{get_project_info().application_name} UI Performance Logging (default: off)")
        self.perf_logging_checkbox.setToolTip("Log per-tick phase timings (DB query, tab updates, etc.) to help diagnose UI lag.")
        self.perf_logging_checkbox.setChecked(to_bool_strict(pref.perf_logging))
        self.perf_logging_checkbox.stateChanged.connect(self.update_perf_logging)
        expert_layout.addWidget(self.perf_logging_checkbox)

        layout.addWidget(expert_group)

    def update_verbose(self):
        """Persist the verbose checkbox state to preferences."""
        pref = get_pref()
        pref.verbose = self.verbose_checkbox.isChecked()

    def update_perf_logging(self):
        """Persist the performance-logging checkbox state to preferences."""
        pref = get_pref()
        pref.perf_logging = self.perf_logging_checkbox.isChecked()

    def update_resume_skip_put_check(self):
        """Persist the resume-skip-PUT-check checkbox and keep run_mode consistent."""
        pref = get_pref()
        checked = self.resume_skip_put_check_checkbox.isChecked()
        pref.resume_skip_put_check = checked
        if pref.run_mode != RunMode.RESTART:
            pref.run_mode = RunMode.RESUME if checked else RunMode.CHECK

    def update_processes(self, value: str):
        """Persist the process-count value to preferences."""
        pref = get_pref()
        if value.isnumeric():
            pref.processes = int(value)

    def update_refresh_rate(self, value: str):
        """Persist the refresh-rate value (clamped to *minimum_refresh_rate*)."""
        pref = get_pref()
        try:
            pref.refresh_rate = max(float(value), minimum_refresh_rate)
        except ValueError:
            pass

    def _validate_utilization_thresholds(self):
        """Warn if the low threshold exceeds the high threshold."""
        pref = get_pref()
        if pref.utilization_low_threshold > pref.utilization_high_threshold:
            log.warning("Low utilization threshold is greater than high utilization threshold")

    def update_utilization_high_threshold(self, value: str):
        """Persist the high-utilization threshold and validate against the low threshold."""
        pref = get_pref()
        try:
            pref.utilization_high_threshold = float(value)
        except ValueError:
            pass
        self._validate_utilization_thresholds()

    def update_utilization_low_threshold(self, value: str):
        """Persist the low-utilization threshold and validate against the high threshold."""
        pref = get_pref()
        try:
            pref.utilization_low_threshold = float(value)
        except ValueError:
            pass
        self._validate_utilization_thresholds()

    def update_commit_warning_threshold(self, value: str):
        """Persist the commit-charge warning threshold (fraction of the commit limit)."""
        pref = get_pref()
        try:
            pref.commit_warning_threshold = float(value)
        except ValueError:
            pass

    def update_stall_detection_enabled(self):
        """Persist the stall-detection (watchdog) enable checkbox."""
        get_pref().stall_detection_enabled = self.stall_detection_enabled_checkbox.isChecked()

    def update_stall_warn(self, *_args):
        """Persist the stall warn window (value + unit) from its two widgets."""
        pref = get_pref()
        try:
            pref.stall_warn_value = max(float(self.stall_warn_value_lineedit.text()), 0.0)
        except ValueError:
            return
        pref.stall_warn_unit = self.stall_warn_unit_combo.currentText()

    def update_cpu_active_epsilon(self, value: str):
        """Persist the CPU idle epsilon (percent below which a subtree counts as idle)."""
        pref = get_pref()
        try:
            pref.cpu_active_epsilon = max(float(value), 0.0)
        except ValueError:
            pass

    def update_auto_force_stop_on_stall(self):
        """Persist the opt-in automatic Force-stop & reset on stall."""
        get_pref().auto_force_stop_on_stall = self.auto_force_stop_on_stall_checkbox.isChecked()

    def update_stall_kill(self, *_args):
        """Persist the stall escalation delay (value + unit); warn if it does not exceed the warn window."""
        pref = get_pref()
        try:
            pref.stall_kill_value = max(float(self.stall_kill_value_lineedit.text()), 0.0)
        except ValueError:
            return
        pref.stall_kill_unit = self.stall_kill_unit_combo.currentText()
        if duration_to_seconds(pref.stall_kill_value, pref.stall_kill_unit) <= duration_to_seconds(pref.stall_warn_value, pref.stall_warn_unit):
            log.warning("Stall kill window must exceed the stall warn window; automatic escalation will be disabled")

    def update_process_count_gate_enabled(self):
        """Persist the process-count admission gate enable checkbox."""
        get_pref().process_count_gate_enabled = self.process_count_gate_enabled_checkbox.isChecked()

    def update_max_descendant_processes(self, value: str):
        """Persist the process-count admission ceiling."""
        pref = get_pref()
        if value.isnumeric():
            pref.max_descendant_processes = max(int(value), 1)

    def update_commit_gate_enabled(self):
        """Persist the commit-charge admission gate enable checkbox."""
        get_pref().commit_gate_enabled = self.commit_gate_enabled_checkbox.isChecked()

    def update_commit_gate_threshold(self, value: str):
        """Persist the commit-charge admission threshold (fraction of the commit limit)."""
        pref = get_pref()
        try:
            pref.commit_gate_threshold = float(value)
        except ValueError:
            pass

    def update_tooltip_line_limit(self, value: str):
        """Persist the tooltip line limit (clamped to *minimum_tooltip_line_limit*)."""
        pref = get_pref()
        if value.isnumeric():
            pref.tooltip_line_limit = max(int(value), minimum_tooltip_line_limit)

    def update_chart_window_minutes(self, value: str):
        """Persist the Run-tab system-metrics chart window (clamped to *minimum_chart_window_minutes*)."""
        pref = get_pref()
        try:
            pref.chart_window_minutes = max(float(value), minimum_chart_window_minutes)
        except ValueError:
            pass

    def update_graph_font_size(self, value: str):
        """Persist the Progress Graph font size (clamped to *minimum_graph_font_size*)."""
        pref = get_pref()
        if value.isnumeric():
            pref.graph_font_size = max(int(value), minimum_graph_font_size)

    def _commit_target_project_path(self):
        """Persist the edited target-project (PUT) path; empty input falls back to the workspace dir."""
        new_value = self.target_project_path_lineedit.text().strip()
        if not new_value:
            # Empty means "use the launch directory" — clear the stored override and reflect the resolved path.
            get_pref().put_path = ""
            self._active_put_path = str(get_active_put_path())
            self.target_project_path_lineedit.setText(self._active_put_path)
            return
        new_path = Path(new_value).resolve()
        if str(new_path) == self._active_put_path:
            return  # no change
        set_active_put_path(new_path)
        self._active_put_path = str(new_path)
        self.target_project_path_lineedit.setText(self._active_put_path)

    def _browse_target_project_path(self):
        """Open a directory picker to choose the target project (PUT) path."""
        start = self.target_project_path_lineedit.text().strip() or self._active_put_path
        selected = QFileDialog.getExistingDirectory(self, "Select target project directory", start)
        if selected:
            self.target_project_path_lineedit.setText(selected)
            self._commit_target_project_path()

    def refresh_target_project_path(self):
        """Re-read the configured PUT into the field (e.g. after the missing-path dialog set it)."""
        self._active_put_path = str(get_active_put_path())
        self.target_project_path_lineedit.setText(self._active_put_path)

    def showEvent(self, event):
        """Refresh the PUT field on each show so it always reflects the current preference.

        The missing-path dialog (run-time or startup) can change the PUT out from under this tab;
        refreshing on show keeps the field current and avoids re-committing a stale path.
        """
        self.refresh_target_project_path()
        super().showEvent(event)

    def update_test_results_db_dir(self, value: str):
        """Persist the test-results DB directory override (empty = workspace-local default)."""
        pref = get_pref()
        pref.test_results_db_dir = value.strip()

    def _browse_test_results_db_dir(self):
        """Open a directory picker to choose the test-results DB directory."""
        pref = get_pref()
        start = pref.test_results_db_dir or str(get_default_data_dir())
        selected = QFileDialog.getExistingDirectory(self, "Select test results DB directory", start)
        if selected:
            self.test_results_db_dir_lineedit.setText(selected)
