from typing import Callable

from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel, QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator, QDoubleValidator

from tobool import to_bool_strict

from pytest_fly.preferences import get_pref, scheduler_time_quantum_default, refresh_rate_default, utilization_high_threshold_default, utilization_low_threshold_default
from pytest_fly.platform.platform_info import get_performance_core_count
from pytest_fly.logger import get_logger
from pytest_fly.gui.gui_util import get_text_dimensions

log = get_logger()

minimum_scheduler_time_quantum = 0.1
minimum_refresh_rate = 1.0


class Configuration(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Configuration")

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setLayout(layout)

        pref = get_pref()

        # Verbose option
        self.verbose_checkbox = QCheckBox("Verbose")
        self.verbose_checkbox.setChecked(to_bool_strict(pref.verbose))
        self.verbose_checkbox.stateChanged.connect(self.update_verbose)
        layout.addWidget(self.verbose_checkbox)

        layout.addWidget(QLabel(""))  # space

        # Processes option
        self.processes_label = QLabel(f"Processes (recommended: {get_performance_core_count()})")
        layout.addWidget(self.processes_label)
        self.processes_lineedit = QLineEdit()
        self.processes_lineedit.setText(str(pref.processes))
        self.processes_lineedit.setValidator(QIntValidator())  # only integers allowed
        processes_width = get_text_dimensions(4 * "X", True)  # 4 digits for number of processes should be plenty
        self.processes_lineedit.setFixedWidth(processes_width.width())
        self.processes_lineedit.textChanged.connect(self.update_processes)
        layout.addWidget(self.processes_lineedit)

        layout.addWidget(QLabel(""))  # space

        # Scheduler Time Quantum option
        self.scheduler_time_quantum_label = QLabel(f"Scheduler Time Quantum (seconds, {minimum_scheduler_time_quantum} minimum, {scheduler_time_quantum_default} default)")
        layout.addWidget(self.scheduler_time_quantum_label)
        self.scheduler_time_quantum_lineedit = QLineEdit()
        self.scheduler_time_quantum_lineedit.setText(str(pref.scheduler_time_quantum))
        self.scheduler_time_quantum_lineedit.setValidator(QDoubleValidator())  # allow floats
        quantum_width = get_text_dimensions(4 * "X", True)  # 4 digits for time quantum should be plenty
        self.scheduler_time_quantum_lineedit.setFixedWidth(quantum_width.width())
        self.scheduler_time_quantum_lineedit.textChanged.connect(self.update_scheduler_time_quantum)
        layout.addWidget(self.scheduler_time_quantum_lineedit)

        layout.addWidget(QLabel(""))  # space

        # Refresh Rate option
        self.refresh_rate_label = QLabel(f"Refresh Rate (seconds, {minimum_refresh_rate} minimum, {refresh_rate_default} default)")
        layout.addWidget(self.refresh_rate_label)
        self.refresh_rate_lineedit = QLineEdit()
        self.refresh_rate_lineedit.setText(str(pref.refresh_rate))
        self.refresh_rate_lineedit.setValidator(QDoubleValidator())  # allow floats
        refresh_rate_width = get_text_dimensions(4 * "X", True)  # 4 digits for refresh rate should be plenty
        self.refresh_rate_lineedit.setFixedWidth(refresh_rate_width.width())
        self.refresh_rate_lineedit.textChanged.connect(self.update_refresh_rate)
        layout.addWidget(self.refresh_rate_lineedit)

        layout.addWidget(QLabel(""))  # space

        # utilization thresholds
        self.utilization_high_threshold_label = QLabel(f"High Utilization Threshold (0.0-1.0, {utilization_high_threshold_default} default)")
        layout.addWidget(self.utilization_high_threshold_label)
        self.utilization_high_threshold_lineedit = QLineEdit()
        self.utilization_high_threshold_lineedit.setText(str(pref.utilization_high_threshold))
        self.utilization_high_threshold_lineedit.setValidator(QDoubleValidator())  # allow floats
        self.utilization_high_threshold_lineedit.setFixedWidth(get_text_dimensions(4 * "X", True).width())
        self.utilization_high_threshold_lineedit.textChanged.connect(self.update_utilization_high_threshold)
        layout.addWidget(self.utilization_high_threshold_lineedit)

        self.update_utilization_low_threshold_label = QLabel(f"Low Utilization Threshold (0.0-1.0, {utilization_low_threshold_default} default)")
        layout.addWidget(self.update_utilization_low_threshold_label)
        self.utilization_low_threshold_lineedit = QLineEdit()
        self.utilization_low_threshold_lineedit.setText(str(pref.utilization_low_threshold))
        self.utilization_low_threshold_lineedit.setValidator(QDoubleValidator())  # allow floats
        self.utilization_low_threshold_lineedit.setFixedWidth(get_text_dimensions(4 * "X", True).width())
        self.utilization_low_threshold_lineedit.textChanged.connect(self.update_utilization_low_threshold)
        layout.addWidget(self.utilization_low_threshold_lineedit)

    def update_verbose(self):
        pref = get_pref()
        pref.verbose = self.verbose_checkbox.isChecked()

    def update_processes(self, value: str):
        pref = get_pref()
        if value.isnumeric():
            pref.processes = int(value)  # validator should ensure this is an integer

    def update_scheduler_time_quantum(self, value: str):
        pref = get_pref()
        try:
            pref.scheduler_time_quantum = max(float(value), minimum_scheduler_time_quantum)  # validator should ensure this is a float
        except ValueError:
            pass

    def update_refresh_rate(self, value: str):
        pref = get_pref()
        try:
            pref.refresh_rate = max(float(value), minimum_refresh_rate)  # validator should ensure this is a float
        except ValueError:
            pass

    def update_utilization_high_threshold(self, value: str):
        pref = get_pref()
        try:
            pref.utilization_high_threshold = float(value)  # validator should ensure this is a float
        except ValueError:
            pass
        if pref.utilization_low_threshold > pref.utilization_high_threshold:
            log.warning("Low utilization threshold is greater than high utilization threshold")

    def update_utilization_low_threshold(self, value: str):
        pref = get_pref()
        try:
            pref.utilization_low_threshold = float(value)  # validator should ensure this is a float
        except ValueError:
            pass
        if pref.utilization_low_threshold > pref.utilization_high_threshold:
            log.warning("Low utilization threshold is greater than high utilization threshold")
