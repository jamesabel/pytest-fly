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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from tobool import to_bool_strict

from pytest_fly.colors import ERROR_ACCENT
from pytest_fly.gui.configuration_tab.ordering_aspects_widget import OrderingAspectsWidget
from pytest_fly.gui.gui_util import get_text_dimensions
from pytest_fly.interfaces import RunMode
from pytest_fly.logger import get_logger
from pytest_fly.paths import get_default_data_dir
from pytest_fly.platform.platform_info import get_performance_core_count
from pytest_fly.preferences import (
    TIME_UNITS,
    auto_force_stop_on_stall_default,
    chart_window_minutes_default,
    commit_gate_enabled_default,
    commit_gate_threshold_default,
    commit_warning_threshold_default,
    cpu_active_epsilon_default,
    cpu_gate_enabled_default,
    cpu_gate_threshold_default,
    duration_to_seconds,
    get_active_put_path,
    get_pref,
    graph_font_size_default,
    log_tab_line_limit_default,
    max_descendant_processes_default,
    process_count_gate_enabled_default,
    refresh_rate_default,
    resource_guard_commit_threshold_default,
    resource_guard_enabled_default,
    resource_guard_min_free_disk_gb_default,
    set_active_put_path,
    stall_detection_enabled_default,
    stall_kill_unit_default,
    stall_kill_value_default,
    stall_warn_unit_default,
    stall_warn_value_default,
    tooltip_line_limit_default,
    utilization_high_threshold_default,
    utilization_low_threshold_default,
)
from pytest_fly.project_info import get_project_info

log = get_logger()

minimum_refresh_rate = 1.0
minimum_tooltip_line_limit = 1
minimum_chart_window_minutes = 0.5
minimum_graph_font_size = 6
minimum_log_tab_line_limit = 100


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


def _add_pref_checkbox(layout: QVBoxLayout, label_text: str, checked, on_changed: Callable[[], None], tooltip: str = "") -> QCheckBox:
    """Create a checkbox wired to a persistence slot and add it to *layout*.

    Eliminates the repeated construct + tooltip + setChecked + connect + addWidget
    pattern used for each boolean preference.

    :param layout: Parent layout to append the checkbox to.
    :param label_text: Checkbox label.
    :param checked: Current preference value (anything ``to_bool_strict`` accepts).
    :param on_changed: Slot connected to ``stateChanged``.
    :param tooltip: Optional hover text.
    :return: The created :class:`QCheckBox`.
    """
    checkbox = QCheckBox(label_text)
    if tooltip:
        checkbox.setToolTip(tooltip)
    checkbox.setChecked(to_bool_strict(checked))
    checkbox.stateChanged.connect(on_changed)
    layout.addWidget(checkbox)
    return checkbox


def _add_validation_label(layout: QVBoxLayout) -> QLabel:
    """Create a hidden red validation label; slots show it when a cross-field invariant breaks."""
    label = QLabel("")
    label.setStyleSheet(f"color: {ERROR_ACCENT.name()};")
    label.setWordWrap(True)
    label.setVisible(False)
    layout.addWidget(label)
    return label


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

        # Restore-defaults control, kept visible at the top of the tab.
        defaults_row = QHBoxLayout()
        defaults_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.restore_defaults_button = QPushButton("Restore Defaults")
        self.restore_defaults_button.setToolTip(
            "Reset every setting on this tab to its default value — including the target project\npath and the test-results DB directory. Asks for confirmation first."
        )
        self.restore_defaults_button.clicked.connect(self.restore_defaults)
        defaults_row.addWidget(self.restore_defaults_button)
        layout.addLayout(defaults_row)

        layout.addWidget(QLabel(""))  # space

        # Resume-mode behavior option
        self.resume_skip_put_check_checkbox = _add_pref_checkbox(
            layout,
            "Resume Without Program Check (default: off)",
            pref.resume_skip_put_check,
            self.update_resume_skip_put_check,
            tooltip=(
                "When unchecked, pytest-fly checks the program under test (PUT) for modifications\n"
                "and runs a full Restart if the PUT has changed.\n"
                "When checked, pytest-fly forces a Resume even if the PUT has changed."
            ),
        )

        layout.addWidget(QLabel(""))  # space

        self.ordering_aspects_widget = OrderingAspectsWidget(self)
        layout.addWidget(self.ordering_aspects_widget)

        layout.addWidget(QLabel(""))  # space

        # Numeric preference fields — use the shared helper to avoid repetition.
        self.processes_lineedit = _add_labeled_lineedit(
            layout,
            f"Processes (recommended: {get_performance_core_count()})",
            str(pref.processes),
            QIntValidator(),
            self.update_processes,
            tooltip="Number of test modules run in parallel when parallelism is set to Parallel.\nTakes effect immediately, even mid-run. Minimum 1.",
        )

        layout.addWidget(QLabel(""))  # space

        self.refresh_rate_lineedit = _add_labeled_lineedit(
            layout,
            f"Refresh Rate (seconds, {minimum_refresh_rate} minimum, {refresh_rate_default} default)",
            str(pref.refresh_rate),
            QDoubleValidator(),
            self.update_refresh_rate,
            tooltip="How often the GUI refreshes from the results database. Lower is smoother but uses more CPU.",
        )

        layout.addWidget(QLabel(""))  # space

        utilization_tooltip = "Colors the Table tab's CPU column: red above the high threshold, yellow above the low\nthreshold. Values are clamped into 0.0-1.0."
        high_label = f"High Utilization Threshold (0.0-1.0, {utilization_high_threshold_default} default)"
        self.utilization_high_threshold_lineedit = _add_labeled_lineedit(
            layout, high_label, str(pref.utilization_high_threshold), QDoubleValidator(), self.update_utilization_high_threshold, tooltip=utilization_tooltip
        )

        low_label = f"Low Utilization Threshold (0.0-1.0, {utilization_low_threshold_default} default)"
        self.utilization_low_threshold_lineedit = _add_labeled_lineedit(
            layout, low_label, str(pref.utilization_low_threshold), QDoubleValidator(), self.update_utilization_low_threshold, tooltip=utilization_tooltip
        )
        # Cross-field validation shown in the UI (not just the log): low must not exceed high.
        self.utilization_warning_label = _add_validation_label(layout)

        layout.addWidget(QLabel(""))  # space

        commit_label = f"Commit Charge Warning Threshold (0.0-1.0, {commit_warning_threshold_default} default)"
        self.commit_warning_threshold_lineedit = _add_labeled_lineedit(
            layout,
            commit_label,
            str(pref.commit_warning_threshold),
            QDoubleValidator(),
            self.update_commit_warning_threshold,
            tooltip="The Run tab's commit-charge warning latches when system commit charge crosses this\nfraction of the commit limit. Clamped into 0.0-1.0.",
        )

        layout.addWidget(QLabel(""))  # space

        tooltip_label = f"Tooltip Line Limit (min {minimum_tooltip_line_limit}, {tooltip_line_limit_default} default)"
        self.tooltip_line_limit_lineedit = _add_labeled_lineedit(
            layout,
            tooltip_label,
            str(pref.tooltip_line_limit),
            QIntValidator(),
            self.update_tooltip_line_limit,
            char_width=6,
            tooltip="Maximum lines of pytest output shown in a hover tooltip before truncation.",
        )

        layout.addWidget(QLabel(""))  # space

        chart_window_label = f"System Metrics Chart Window (minutes, {minimum_chart_window_minutes} minimum, {chart_window_minutes_default} default)"
        self.chart_window_minutes_lineedit = _add_labeled_lineedit(
            layout,
            chart_window_label,
            str(pref.chart_window_minutes),
            QDoubleValidator(),
            self.update_chart_window_minutes,
            char_width=6,
            tooltip="Width of the Run tab's System Performance chart time window.",
        )

        layout.addWidget(QLabel(""))  # space

        graph_font_size_label = f"Progress Graph Font Size (points, {minimum_graph_font_size} minimum, {graph_font_size_default} default)"
        self.graph_font_size_lineedit = _add_labeled_lineedit(
            layout,
            graph_font_size_label,
            str(pref.graph_font_size),
            QIntValidator(),
            self.update_graph_font_size,
            char_width=6,
            tooltip="Point size of the font used in the Progress Graph tab. Applies on the next refresh tick.",
        )

        layout.addWidget(QLabel(""))  # space

        log_tab_line_limit_label = f"Log Tab Line Limit (min {minimum_log_tab_line_limit}, {log_tab_line_limit_default} default)"
        self.log_tab_line_limit_lineedit = _add_labeled_lineedit(
            layout,
            log_tab_line_limit_label,
            str(pref.log_tab_line_limit),
            QIntValidator(),
            self.update_log_tab_line_limit,
            char_width=7,
            tooltip="Maximum log lines retained and displayed in the Log tab (bounds memory over a long\nsession). The oldest lines are dropped first. Applies on the next refresh tick.",
        )

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
        self.test_results_db_dir_lineedit.setToolTip("Where the test-results SQLite DB is stored. Leave empty for the workspace-local default.")
        # Commit on editingFinished (matching the Target Project Path field) rather than on
        # every keystroke, so a half-typed path is never persisted.
        self.test_results_db_dir_lineedit.editingFinished.connect(lambda: self.update_test_results_db_dir(self.test_results_db_dir_lineedit.text()))
        results_dir_row.addWidget(self.test_results_db_dir_lineedit)
        self.test_results_db_dir_browse = QPushButton("Browse…")
        self.test_results_db_dir_browse.clicked.connect(self._browse_test_results_db_dir)
        results_dir_row.addWidget(self.test_results_db_dir_browse)
        layout.addLayout(results_dir_row)
        results_dir_hint = QLabel("Applies on restart.")
        results_dir_hint.setStyleSheet("color: gray;")
        layout.addWidget(results_dir_hint)

        # Liveness / recovery group — the stall watchdog. Lives in the right column (see the
        # two-column content layout above) so the tall set of options uses the available
        # horizontal room instead of overflowing vertically.
        # See docs/pytest-fly-liveness-recovery-spec.md.
        liveness_group = QGroupBox("Liveness / Recovery")
        liveness_group.setToolTip(
            "Detect and recover from wedged runs. The stall watchdog is advisory only (a banner);\nit never kills a test on its own unless automatic escalation is explicitly enabled."
        )
        liveness_layout = QVBoxLayout()
        liveness_group.setLayout(liveness_layout)

        self.stall_detection_enabled_checkbox = _add_pref_checkbox(
            liveness_layout,
            "Stall Detection (advisory banner, default: on)",
            pref.stall_detection_enabled,
            self.update_stall_detection_enabled,
            tooltip=(
                "Watches for a wedged run — a hung test whose nested process tree has deadlocked, which\n"
                "would otherwise keep pytest-fly reporting 'running' forever and never re-enable Run.\n\n"
                "Flags the run as stalled (a banner only — nothing is killed) when, for the whole Stall\n"
                "Warn Window, no test starts or finishes AND no in-flight test uses any CPU. A test that\n"
                "is genuinely working keeps using CPU and never trips this, no matter how long it runs.\n\n"
                "When stalled, click Force Stop to recover: in-flight processes are killed, leftover tests\n"
                "are marked stopped, and Run re-enables — without killing pytest-fly from the OS."
            ),
        )

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

        self.auto_force_stop_on_stall_checkbox = _add_pref_checkbox(
            liveness_layout,
            # "&&" renders a literal ampersand — a single "&" in a checkbox label is a Qt
            # keyboard-mnemonic marker and displays as an underlined "R" instead.
            "Auto Force-stop && Reset on Stall (default: off)",
            pref.auto_force_stop_on_stall,
            self.update_auto_force_stop_on_stall,
            tooltip=(
                "When OFF (default), a stall only shows a banner — you click Force Stop to recover.\n\n"
                "When ON, after the Stall Kill Window of continuous stalling the run is automatically\n"
                "force-stopped and reset (useful for unattended CI). Leave OFF if your tests can\n"
                "legitimately block on slow network/disk I/O, since that also reads as idle and could\n"
                "trigger a false recovery."
            ),
        )

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
        # Cross-field validation shown in the UI: the kill window must exceed the warn window,
        # otherwise automatic escalation is silently disabled — say so where the user can see it.
        self.stall_kill_warning_label = _add_validation_label(liveness_layout)

        right_column.addWidget(liveness_group)

        # Admission gates group — dispatch throttles, in their own labeled box. Distinct from
        # Liveness / Recovery (recovering a wedged run) and from the Resource Guard (stopping a
        # run): the gates only *pace* a healthy run by deferring the start of new tests.
        gates_group = QGroupBox("Admission Gates")
        gates_group.setToolTip(
            "Throttle when new tests are dispatched. Before starting another test, pytest-fly\n"
            "waits while any enabled gate is over its limit (all enabled gates must allow a test\n"
            "before it starts).\n\n"
            "Gates only defer starting new tests — they never pause or cap a running test — and\n"
            "at least one test always runs so the suite can't deadlock behind a gate. All gates\n"
            "are off by default."
        )
        gates_layout = QVBoxLayout()
        gates_group.setLayout(gates_layout)

        self.process_count_gate_enabled_checkbox = _add_pref_checkbox(
            gates_layout,
            "Process-count Gate (default: off)",
            pref.process_count_gate_enabled,
            self.update_process_count_gate_enabled,
            tooltip=(
                "Throttles runaway process spawning. Before starting another test, pytest-fly waits while\n"
                "the total number of processes in its tree — every test process plus anything those tests\n"
                "spawn (subprocesses, multiprocessing pools) — is at or above 'Max Descendant Processes'.\n\n"
                "Only defers starting new tests; it never caps how long a running test takes, and at least\n"
                "one test always runs so the suite can't deadlock behind the gate. Off by default."
            ),
        )

        self.max_descendant_processes_lineedit = _add_labeled_lineedit(
            gates_layout,
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

        self.commit_gate_enabled_checkbox = _add_pref_checkbox(
            gates_layout,
            "Commit-charge Gate (default: off)",
            pref.commit_gate_enabled,
            self.update_commit_gate_enabled,
            tooltip=(
                "Throttles dispatch by memory commitment rather than process count. Before starting another\n"
                "test, pytest-fly waits while system commit charge (RAM + page file currently committed)\n"
                "exceeds the threshold below.\n\n"
                "Complements the process-count gate; when both are on, both must allow a test before it\n"
                "starts. Only defers new tests, and at least one always runs. Off by default. (Commit\n"
                "charge is read on Windows; on other platforms this gate stays out of the way.)"
            ),
        )

        self.commit_gate_threshold_lineedit = _add_labeled_lineedit(
            gates_layout,
            f"Commit Gate Threshold (0.0-1.0, {commit_gate_threshold_default} default)",
            str(pref.commit_gate_threshold),
            QDoubleValidator(),
            self.update_commit_gate_threshold,
            tooltip=(
                "The fraction of the system commit limit (0.0–1.0) at or above which the commit-charge\n"
                "gate defers starting new tests. For example, 0.90 means 'hold off once commit charge\n"
                "reaches 90% of the limit.' Only used when the Commit-charge Gate is enabled."
            ),
        )

        self.cpu_gate_enabled_checkbox = _add_pref_checkbox(
            gates_layout,
            "CPU Gate (default: off)",
            pref.cpu_gate_enabled,
            self.update_cpu_gate_enabled,
            tooltip=(
                "Throttles dispatch by system-wide CPU utilization. Before starting another test,\n"
                "pytest-fly waits while total CPU usage (from all processes on the machine, not just\n"
                "tests) is above the threshold below — keeping the machine responsive and avoiding\n"
                "timing-sensitive test failures caused by CPU starvation.\n\n"
                "Composes with the other admission gates (all enabled gates must allow a test before it\n"
                "starts). Only defers new tests — it never pauses or caps a running test — and at least\n"
                "one test always runs so the suite can't deadlock behind the gate. Off by default."
            ),
        )

        self.cpu_gate_threshold_lineedit = _add_labeled_lineedit(
            gates_layout,
            f"CPU Gate Threshold (0.0-1.0, {cpu_gate_threshold_default} default)",
            str(pref.cpu_gate_threshold),
            QDoubleValidator(),
            self.update_cpu_gate_threshold,
            tooltip=(
                "The fraction of total system CPU (0.0–1.0) at or above which the CPU gate defers\n"
                "starting new tests. For example, 0.90 means 'hold off while the whole machine is over\n"
                "90% busy.' Only used when the CPU Gate is enabled."
            ),
        )

        right_column.addWidget(gates_group)

        # Resource guard group — background low-resource monitor that automatically soft-stops
        # the run. Kept separate from Liveness / Recovery: that group is about a *wedged* run,
        # this one is about protecting the *machine* (disk and commit space) from a healthy run.
        resource_guard_group = QGroupBox("Resource Guard")
        resource_guard_group.setToolTip(
            "Monitors system resources in the background during a run and automatically requests a\n"
            "soft stop when the system is running low — running tests finish, queued tests do not\n"
            "start. The stop is the same cancelable stop as the Stop button, so it can be overridden\n"
            "with Cancel Stop. Off by default."
        )
        resource_guard_layout = QVBoxLayout()
        resource_guard_group.setLayout(resource_guard_layout)

        self.resource_guard_enabled_checkbox = _add_pref_checkbox(
            resource_guard_layout,
            "Low-resource Auto Stop (default: off)",
            pref.resource_guard_enabled,
            self.update_resource_guard_enabled,
            tooltip=(
                "When enabled, pytest-fly watches free disk space (on the drive holding its data\n"
                "directory) and system commit space (RAM + page file) while a run is in progress.\n"
                "If either stays past its threshold, the run is soft-stopped: running tests finish,\n"
                "queued tests are not started. Use Cancel Stop to override and keep running.\n\n"
                "Triggers at most once per run, and never fires when a signal is unavailable\n"
                "(e.g. commit space on non-Windows platforms). Applies on the next run."
            ),
        )

        self.resource_guard_min_free_disk_gb_lineedit = _add_labeled_lineedit(
            resource_guard_layout,
            f"Minimum Free Disk Space (GB, {_format_number(resource_guard_min_free_disk_gb_default)} default, 0 disables)",
            _format_number(pref.resource_guard_min_free_disk_gb),
            QDoubleValidator(),
            self.update_resource_guard_min_free_disk_gb,
            char_width=7,
            tooltip=(
                "The run is soft-stopped when free space on the drive holding the pytest-fly data\n"
                "directory (test-results DB and coverage data) drops below this many GB.\n"
                "Set to 0 to disable the disk check. Only used when Low-resource Auto Stop is enabled."
            ),
        )

        self.resource_guard_commit_threshold_lineedit = _add_labeled_lineedit(
            resource_guard_layout,
            f"Commit Space Stop Threshold (0.0-1.0, {resource_guard_commit_threshold_default} default)",
            str(pref.resource_guard_commit_threshold),
            QDoubleValidator(),
            self.update_resource_guard_commit_threshold,
            tooltip=(
                "The run is soft-stopped when system commit charge (RAM + page file currently\n"
                "committed) exceeds this fraction of the commit limit — e.g. 0.95 means 'stop once\n"
                "commit space is 95% used.' Exhausting commit space crashes test workers with\n"
                "page-file errors. Only used when Low-resource Auto Stop is enabled. (Commit charge\n"
                "is read on Windows; on other platforms this check stays out of the way.)"
            ),
        )

        right_column.addWidget(resource_guard_group)

        # Expert group — settings most users should not need to change. Lives at the bottom of
        # the right column (last position, to de-emphasize) rather than the left column, which
        # is the taller of the two and drives the tab's overall height.
        expert_group = QGroupBox("Expert")
        expert_group.setToolTip("Advanced diagnostic options. Normal users should not need to change these.")
        expert_layout = QVBoxLayout()
        expert_group.setLayout(expert_layout)

        self.verbose_checkbox = _add_pref_checkbox(
            expert_layout, "Verbose (default: off)", pref.verbose, self.update_verbose, tooltip="Enable verbose (DEBUG-level) logging for diagnosing pytest-fly itself."
        )

        self.perf_logging_checkbox = _add_pref_checkbox(
            expert_layout,
            f"{get_project_info().application_name} UI Performance Logging (default: off)",
            pref.perf_logging,
            self.update_perf_logging,
            tooltip="Log per-tick phase timings (DB query, tab updates, etc.) to help diagnose UI lag.",
        )

        right_column.addWidget(expert_group)
        right_column.addStretch()

    # ------------------------------------------------------------------
    # Preference-persistence helpers — shared by all the update_* slots below
    # ------------------------------------------------------------------

    def _set_float_pref(self, pref_name: str, value: str, minimum: float | None = None, maximum: float | None = None) -> None:
        """Parse *value* as a float, clamp into [minimum, maximum], and persist it; non-numeric input is ignored."""
        try:
            number = float(value)
        except ValueError:
            return
        if minimum is not None:
            number = max(number, minimum)
        if maximum is not None:
            number = min(number, maximum)
        setattr(get_pref(), pref_name, number)

    def _set_fraction_pref(self, pref_name: str, value: str) -> None:
        """Persist a 0.0-1.0 fraction preference, clamped into range (the labels all say "0.0-1.0")."""
        self._set_float_pref(pref_name, value, minimum=0.0, maximum=1.0)

    def _set_int_pref(self, pref_name: str, value: str, minimum: int | None = None) -> None:
        """Parse *value* as an int, clamp to *minimum*, and persist it; non-numeric input is ignored."""
        if not value.isnumeric():
            return
        number = int(value)
        if minimum is not None:
            number = max(number, minimum)
        setattr(get_pref(), pref_name, number)

    def _set_bool_pref(self, pref_name: str, checkbox: QCheckBox) -> None:
        """Persist a checkbox's checked state."""
        setattr(get_pref(), pref_name, checkbox.isChecked())

    # ------------------------------------------------------------------
    # Persistence slots
    # ------------------------------------------------------------------

    def update_verbose(self):
        """Persist the verbose checkbox state to preferences."""
        self._set_bool_pref("verbose", self.verbose_checkbox)

    def update_perf_logging(self):
        """Persist the performance-logging checkbox state to preferences."""
        self._set_bool_pref("perf_logging", self.perf_logging_checkbox)

    def update_resume_skip_put_check(self):
        """Persist the resume-skip-PUT-check checkbox and keep run_mode consistent."""
        pref = get_pref()
        checked = self.resume_skip_put_check_checkbox.isChecked()
        pref.resume_skip_put_check = checked
        if pref.run_mode != RunMode.RESTART:
            pref.run_mode = RunMode.RESUME if checked else RunMode.CHECK

    def update_processes(self, value: str):
        """Persist the process-count value (minimum 1 — 0 workers would make a run do nothing)."""
        self._set_int_pref("processes", value, minimum=1)

    def update_refresh_rate(self, value: str):
        """Persist the refresh-rate value (clamped to *minimum_refresh_rate*)."""
        self._set_float_pref("refresh_rate", value, minimum=minimum_refresh_rate)

    def _validate_utilization_thresholds(self):
        """Show/clear the in-UI warning when the low threshold exceeds the high threshold."""
        pref = get_pref()
        invalid = pref.utilization_low_threshold > pref.utilization_high_threshold
        if invalid:
            log.warning("Low utilization threshold is greater than high utilization threshold")
            self.utilization_warning_label.setText("Low threshold exceeds the high threshold — the yellow/red coloring will not behave as expected.")
        self.utilization_warning_label.setVisible(invalid)

    def update_utilization_high_threshold(self, value: str):
        """Persist the high-utilization threshold (clamped 0.0-1.0) and validate against the low threshold."""
        self._set_fraction_pref("utilization_high_threshold", value)
        self._validate_utilization_thresholds()

    def update_utilization_low_threshold(self, value: str):
        """Persist the low-utilization threshold (clamped 0.0-1.0) and validate against the high threshold."""
        self._set_fraction_pref("utilization_low_threshold", value)
        self._validate_utilization_thresholds()

    def update_commit_warning_threshold(self, value: str):
        """Persist the commit-charge warning threshold (fraction of the commit limit, clamped 0.0-1.0)."""
        self._set_fraction_pref("commit_warning_threshold", value)

    def update_stall_detection_enabled(self):
        """Persist the stall-detection (watchdog) enable checkbox."""
        self._set_bool_pref("stall_detection_enabled", self.stall_detection_enabled_checkbox)

    def update_stall_warn(self, *_args):
        """Persist the stall warn window (value + unit) from its two widgets."""
        pref = get_pref()
        try:
            pref.stall_warn_value = max(float(self.stall_warn_value_lineedit.text()), 0.0)
        except ValueError:
            return
        pref.stall_warn_unit = self.stall_warn_unit_combo.currentText()
        self._validate_stall_windows()

    def update_cpu_active_epsilon(self, value: str):
        """Persist the CPU idle epsilon (percent below which a subtree counts as idle)."""
        self._set_float_pref("cpu_active_epsilon", value, minimum=0.0)

    def update_auto_force_stop_on_stall(self):
        """Persist the opt-in automatic Force-stop & reset on stall."""
        self._set_bool_pref("auto_force_stop_on_stall", self.auto_force_stop_on_stall_checkbox)

    def _validate_stall_windows(self):
        """Show/clear the in-UI warning when the kill window does not exceed the warn window."""
        pref = get_pref()
        invalid = duration_to_seconds(pref.stall_kill_value, pref.stall_kill_unit) <= duration_to_seconds(pref.stall_warn_value, pref.stall_warn_unit)
        if invalid:
            log.warning("Stall kill window must exceed the stall warn window; automatic escalation will be disabled")
            self.stall_kill_warning_label.setText("Kill window must exceed the warn window — automatic escalation is disabled until it does.")
        self.stall_kill_warning_label.setVisible(invalid)

    def update_stall_kill(self, *_args):
        """Persist the stall escalation delay (value + unit); warn in the UI if it does not exceed the warn window."""
        pref = get_pref()
        try:
            pref.stall_kill_value = max(float(self.stall_kill_value_lineedit.text()), 0.0)
        except ValueError:
            return
        pref.stall_kill_unit = self.stall_kill_unit_combo.currentText()
        self._validate_stall_windows()

    def update_process_count_gate_enabled(self):
        """Persist the process-count admission gate enable checkbox."""
        self._set_bool_pref("process_count_gate_enabled", self.process_count_gate_enabled_checkbox)

    def update_max_descendant_processes(self, value: str):
        """Persist the process-count admission ceiling."""
        self._set_int_pref("max_descendant_processes", value, minimum=1)

    def update_commit_gate_enabled(self):
        """Persist the commit-charge admission gate enable checkbox."""
        self._set_bool_pref("commit_gate_enabled", self.commit_gate_enabled_checkbox)

    def update_commit_gate_threshold(self, value: str):
        """Persist the commit-charge admission threshold (fraction of the commit limit, clamped 0.0-1.0)."""
        self._set_fraction_pref("commit_gate_threshold", value)

    def update_cpu_gate_enabled(self):
        """Persist the CPU-utilization admission gate enable checkbox."""
        self._set_bool_pref("cpu_gate_enabled", self.cpu_gate_enabled_checkbox)

    def update_cpu_gate_threshold(self, value: str):
        """Persist the CPU-utilization admission threshold (fraction of total system CPU, clamped 0.0-1.0)."""
        self._set_fraction_pref("cpu_gate_threshold", value)

    def update_resource_guard_enabled(self):
        """Persist the resource-guard (low-resource automatic soft stop) enable checkbox."""
        self._set_bool_pref("resource_guard_enabled", self.resource_guard_enabled_checkbox)

    def update_resource_guard_min_free_disk_gb(self, value: str):
        """Persist the resource-guard minimum free disk space (GB; 0 disables the disk check)."""
        self._set_float_pref("resource_guard_min_free_disk_gb", value, minimum=0.0)

    def update_resource_guard_commit_threshold(self, value: str):
        """Persist the resource-guard commit-space stop threshold (fraction of the commit limit, clamped 0.0-1.0)."""
        self._set_fraction_pref("resource_guard_commit_threshold", value)

    def update_tooltip_line_limit(self, value: str):
        """Persist the tooltip line limit (clamped to *minimum_tooltip_line_limit*)."""
        self._set_int_pref("tooltip_line_limit", value, minimum=minimum_tooltip_line_limit)

    def update_chart_window_minutes(self, value: str):
        """Persist the Run-tab system-metrics chart window (clamped to *minimum_chart_window_minutes*)."""
        self._set_float_pref("chart_window_minutes", value, minimum=minimum_chart_window_minutes)

    def update_graph_font_size(self, value: str):
        """Persist the Progress Graph font size (clamped to *minimum_graph_font_size*)."""
        self._set_int_pref("graph_font_size", value, minimum=minimum_graph_font_size)

    def update_log_tab_line_limit(self, value: str):
        """Persist the Log tab line limit (clamped to *minimum_log_tab_line_limit*)."""
        self._set_int_pref("log_tab_line_limit", value, minimum=minimum_log_tab_line_limit)

    def restore_defaults(self):
        """Ask for confirmation, then reset every Configuration-tab setting to its default."""
        response = QMessageBox.question(
            self,
            "Restore defaults",
            "Restore every setting on this tab to its default value?\n\nThis includes the target project path and the test-results DB directory.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self._apply_defaults()

    def _apply_defaults(self) -> None:
        """Reset every Configuration-tab preference to its default and refresh the widgets.

        Preferences are written directly (not via the widget signals): a widget whose
        displayed text already equals the default emits no ``textChanged``, so a
        signal-driven reset would silently skip any preference that drifted from its
        widget (e.g. through clamping). The widgets are then updated to match.
        """
        pref = get_pref()

        checkbox_defaults: list[tuple[str, QCheckBox, bool]] = [
            ("resume_skip_put_check", self.resume_skip_put_check_checkbox, False),
            ("stall_detection_enabled", self.stall_detection_enabled_checkbox, stall_detection_enabled_default),
            ("auto_force_stop_on_stall", self.auto_force_stop_on_stall_checkbox, auto_force_stop_on_stall_default),
            ("process_count_gate_enabled", self.process_count_gate_enabled_checkbox, process_count_gate_enabled_default),
            ("commit_gate_enabled", self.commit_gate_enabled_checkbox, commit_gate_enabled_default),
            ("cpu_gate_enabled", self.cpu_gate_enabled_checkbox, cpu_gate_enabled_default),
            ("resource_guard_enabled", self.resource_guard_enabled_checkbox, resource_guard_enabled_default),
            ("verbose", self.verbose_checkbox, False),
            ("perf_logging", self.perf_logging_checkbox, False),
        ]
        for pref_name, checkbox, default in checkbox_defaults:
            setattr(pref, pref_name, default)
            checkbox.setChecked(default)
        # Mirror the resume-checkbox slot's run_mode coupling for the default (unchecked) state.
        if pref.run_mode != RunMode.RESTART:
            pref.run_mode = RunMode.CHECK

        field_defaults: list[tuple[str, QLineEdit, float | int]] = [
            ("processes", self.processes_lineedit, get_performance_core_count()),
            ("refresh_rate", self.refresh_rate_lineedit, refresh_rate_default),
            ("utilization_high_threshold", self.utilization_high_threshold_lineedit, utilization_high_threshold_default),
            ("utilization_low_threshold", self.utilization_low_threshold_lineedit, utilization_low_threshold_default),
            ("commit_warning_threshold", self.commit_warning_threshold_lineedit, commit_warning_threshold_default),
            ("tooltip_line_limit", self.tooltip_line_limit_lineedit, tooltip_line_limit_default),
            ("chart_window_minutes", self.chart_window_minutes_lineedit, chart_window_minutes_default),
            ("graph_font_size", self.graph_font_size_lineedit, graph_font_size_default),
            ("log_tab_line_limit", self.log_tab_line_limit_lineedit, log_tab_line_limit_default),
            ("cpu_active_epsilon", self.cpu_active_epsilon_lineedit, cpu_active_epsilon_default),
            ("max_descendant_processes", self.max_descendant_processes_lineedit, max_descendant_processes_default),
            ("commit_gate_threshold", self.commit_gate_threshold_lineedit, commit_gate_threshold_default),
            ("cpu_gate_threshold", self.cpu_gate_threshold_lineedit, cpu_gate_threshold_default),
            ("resource_guard_min_free_disk_gb", self.resource_guard_min_free_disk_gb_lineedit, resource_guard_min_free_disk_gb_default),
            ("resource_guard_commit_threshold", self.resource_guard_commit_threshold_lineedit, resource_guard_commit_threshold_default),
        ]
        for pref_name, lineedit, default in field_defaults:
            setattr(pref, pref_name, default)
            lineedit.setText(_format_number(default))

        # Stall windows: value + unit pairs.
        pref.stall_warn_value = stall_warn_value_default
        pref.stall_warn_unit = stall_warn_unit_default
        self.stall_warn_value_lineedit.setText(_format_number(stall_warn_value_default))
        self.stall_warn_unit_combo.setCurrentText(stall_warn_unit_default)
        pref.stall_kill_value = stall_kill_value_default
        pref.stall_kill_unit = stall_kill_unit_default
        self.stall_kill_value_lineedit.setText(_format_number(stall_kill_value_default))
        self.stall_kill_unit_combo.setCurrentText(stall_kill_unit_default)

        # Test-ordering aspects back to the built-in seed.
        self.ordering_aspects_widget.reset_to_defaults()

        # Paths: empty means "use the launch directory" / the workspace-local default.
        pref.put_path = ""
        self.refresh_target_project_path()
        pref.test_results_db_dir = ""
        self.test_results_db_dir_lineedit.setText("")

        # The defaults satisfy both cross-field invariants; clear any shown warnings.
        self._validate_utilization_thresholds()
        self._validate_stall_windows()

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
