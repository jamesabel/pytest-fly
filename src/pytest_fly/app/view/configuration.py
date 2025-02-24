from typing import Callable

from PySide6.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QLabel, QLineEdit
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator

from tobool import to_bool_strict

from ..preferences import get_pref
from .gui_util import get_text_dimensions
from ..platform_info import get_performance_core_count
from ..logging import get_logger

log = get_logger()


class Configuration(QWidget):
    def __init__(self, configuration_update_callback: Callable):
        super().__init__()
        self.configuration_update_callback = configuration_update_callback

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

    def update_verbose(self, state: str):
        pref = get_pref()
        pref.verbose = to_bool_strict(state)
        self.configuration_update_callback()

    def update_processes(self, value: str):
        pref = get_pref()
        if value.isnumeric():
            pref.processes = int(value)  # validator should ensure this is an integer
        self.configuration_update_callback()
