"""
Configuration tab — exposes user-editable preferences such as verbosity,
parallelism, refresh rate, and utilization thresholds.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QIntValidator, QValidator
from PySide6.QtWidgets import QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget
from tobool import to_bool_strict

from pytest_fly.gui.about_tab.project_info import get_project_info
from pytest_fly.gui.gui_util import get_text_dimensions
from pytest_fly.interfaces import TestOrder
from pytest_fly.logger import get_logger
from pytest_fly.platform.platform_info import get_performance_core_count
from pytest_fly.preferences import get_pref, refresh_rate_default, tooltip_line_limit_default, utilization_high_threshold_default, utilization_low_threshold_default

log = get_logger()

minimum_refresh_rate = 1.0
minimum_tooltip_line_limit = 1


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

        # Test order option
        self.coverage_order_checkbox = QCheckBox("Order tests by coverage efficiency")
        self.coverage_order_checkbox.setChecked(int(pref.test_order) == TestOrder.COVERAGE)
        self.coverage_order_checkbox.stateChanged.connect(self.update_test_order)
        layout.addWidget(self.coverage_order_checkbox)

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

    def update_test_order(self):
        """Persist the test order preference based on the checkbox state."""
        pref = get_pref()
        pref.test_order = TestOrder.COVERAGE if self.coverage_order_checkbox.isChecked() else TestOrder.PYTEST

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
