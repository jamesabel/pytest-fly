"""
Configuration tab — exposes user-editable preferences such as verbosity,
parallelism, refresh rate, and utilization thresholds.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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
from pytest_fly.platform.platform_info import get_performance_core_count
from pytest_fly.preferences import (
    chart_window_minutes_default,
    get_ordering_aspects,
    get_pref,
    refresh_rate_default,
    set_ordering_aspects,
    tooltip_line_limit_default,
    utilization_high_threshold_default,
    utilization_low_threshold_default,
)

_ordering_aspect_labels: dict[OrderingAspect, str] = {
    OrderingAspect.FAILED_FIRST: "Failed tests first",
    OrderingAspect.NEVER_RUN_FIRST: "Never-run tests first",
    OrderingAspect.LONGEST_PRIOR_FIRST: "Longest prior execution time first",
    OrderingAspect.COVERAGE_EFFICIENCY: "Coverage efficiency (lines/sec)",
}

_ordering_aspect_tooltips: dict[OrderingAspect, str] = {
    OrderingAspect.FAILED_FIRST: "Tests that failed in the previous run run first. Ignored in Restart mode.",
    OrderingAspect.NEVER_RUN_FIRST: "Tests with no record in the database (any program-under-test version) run first.",
    OrderingAspect.LONGEST_PRIOR_FIRST: (
        "Tests with the longest prior passing-run duration run first. Helps parallel runs by starting the\n"
        "critical-path tests earliest; shorter tests backfill the remaining workers. Ignored in Restart mode."
    ),
    OrderingAspect.COVERAGE_EFFICIENCY: ("Tests with the highest lines-covered-per-second run first. Requires prior duration and coverage data. Ignored in Restart mode."),
}


class OrderingAspectsWidget(QGroupBox):
    """Reorderable, per-row-checkable list of test-ordering aspects."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Test Ordering", parent)
        # Hug our content — do not stretch into parent layout whitespace.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip("Top of the list is highest priority. Check a row to enable that aspect; use Up/Down to reorder.")

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
        self._list.itemChanged.connect(self._persist)

    def _resize_list_to_content(self) -> None:
        """Fix the list widget's size to exactly fit its rows and longest label.

        ``sizeHintForColumn`` only measures the text, not the leading check
        indicator Qt draws when ``ItemIsUserCheckable`` is set.  We add the
        style's indicator width plus a small per-row horizontal padding so
        long labels are never clipped.
        """
        count = self._list.count()
        if count == 0:
            return
        style = self._list.style()
        indicator_width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, self._list)
        # Horizontal margin Qt puts around item text inside a QAbstractItemView.
        item_margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, self._list) * 2 + 8
        fm = self._list.fontMetrics()
        text_width = max(fm.horizontalAdvance(_ordering_aspect_labels[a]) for a in _ordering_aspect_labels)
        row_height = self._list.sizeHintForRow(0)
        frame = 2 * self._list.frameWidth()
        width = text_width + indicator_width + item_margin + frame
        self._list.setFixedSize(width, row_height * count + frame)

    def _populate_from_prefs(self) -> None:
        pref = get_pref()
        self._list.clear()
        for aspect, enabled in get_ordering_aspects(pref):
            item = QListWidgetItem(_ordering_aspect_labels[aspect])
            item.setToolTip(_ordering_aspect_tooltips[aspect])
            item.setData(Qt.ItemDataRole.UserRole, aspect.value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
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

    def _persist(self) -> None:
        aspects: list[tuple[OrderingAspect, bool]] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            aspect = OrderingAspect(item.data(Qt.ItemDataRole.UserRole))
            enabled = item.checkState() == Qt.CheckState.Checked
            aspects.append((aspect, enabled))
        set_ordering_aspects(get_pref(), aspects)


log = get_logger()

minimum_refresh_rate = 1.0
minimum_tooltip_line_limit = 1
minimum_chart_window_minutes = 0.5


def _add_labeled_lineedit(
    layout: QVBoxLayout,
    label_text: str,
    initial_value: str,
    validator: QValidator,
    on_changed: Callable[[str], None],
    char_width: int = 4,
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
    :return: The created :class:`QLineEdit`.
    """
    layout.addWidget(QLabel(label_text))
    lineedit = QLineEdit()
    lineedit.setText(initial_value)
    lineedit.setValidator(validator)
    lineedit.setFixedWidth(get_text_dimensions(char_width * "X", True).width())
    lineedit.textChanged.connect(on_changed)
    layout.addWidget(lineedit)
    return lineedit


class Configuration(QWidget):
    """Configuration tab exposing user-editable preferences (verbose, processes, refresh rate, thresholds)."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Configuration")

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setLayout(layout)

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

        tooltip_label = f"Tooltip Line Limit (min {minimum_tooltip_line_limit}, {tooltip_line_limit_default} default)"
        self.tooltip_line_limit_lineedit = _add_labeled_lineedit(layout, tooltip_label, str(pref.tooltip_line_limit), QIntValidator(), self.update_tooltip_line_limit, char_width=6)

        layout.addWidget(QLabel(""))  # space

        chart_window_label = f"System Metrics Chart Window (minutes, {minimum_chart_window_minutes} minimum, {chart_window_minutes_default} default)"
        self.chart_window_minutes_lineedit = _add_labeled_lineedit(
            layout, chart_window_label, str(pref.chart_window_minutes), QDoubleValidator(), self.update_chart_window_minutes, char_width=6
        )

        layout.addWidget(QLabel(""))  # space

        # Target project path — empty means auto-detect from the current working directory at run time.
        layout.addWidget(QLabel("Target Project Path (empty = auto-detect from current directory)"))
        target_path_row = QHBoxLayout()
        self.target_project_path_lineedit = QLineEdit()
        self.target_project_path_lineedit.setText(pref.target_project_path)
        self.target_project_path_lineedit.setPlaceholderText("(auto-detect)")
        self.target_project_path_lineedit.textChanged.connect(self.update_target_project_path)
        target_path_row.addWidget(self.target_project_path_lineedit)
        self.target_project_path_browse = QPushButton("Browse…")
        self.target_project_path_browse.clicked.connect(self._browse_target_project_path)
        target_path_row.addWidget(self.target_project_path_browse)
        layout.addLayout(target_path_row)

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

    def update_target_project_path(self, value: str):
        """Persist the target-project path override (empty = auto-detect)."""
        pref = get_pref()
        pref.target_project_path = value.strip()

    def _browse_target_project_path(self):
        """Open a directory picker to choose the target project path."""
        pref = get_pref()
        start = pref.target_project_path or ""
        selected = QFileDialog.getExistingDirectory(self, "Select target project directory", start)
        if selected:
            self.target_project_path_lineedit.setText(selected)
