from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QRadioButton, QButtonGroup

from pytest_fly.preferences import get_pref, ParallelismControl


class ParallelismControlBox(QGroupBox):

    def __init__(self, parent):
        super().__init__("Parallelism", parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        pref = get_pref()

        self.parallelism_group = QButtonGroup(self)
        self.parallelism_serial = QRadioButton("Serial")
        self.parallelism_serial.setToolTip("Run tests one at a time.")
        self.parallelism_parallel = QRadioButton("Parallel")
        self.parallelism_dynamic = QRadioButton("Dynamic")
        self.parallelism_dynamic.setToolTip("Automatically determine maximum number\n of processes to run in parallel, while\nattempting to avoid high utilization thresholds.")

        self.parallelism_group.addButton(self.parallelism_serial)
        self.parallelism_group.addButton(self.parallelism_parallel)
        self.parallelism_group.addButton(self.parallelism_dynamic)

        layout.addWidget(self.parallelism_serial)
        layout.addWidget(self.parallelism_parallel)
        layout.addWidget(self.parallelism_dynamic)

        self.parallelism_serial.setChecked(pref.parallelism == ParallelismControl.SERIAL)
        self.parallelism_parallel.setChecked(pref.parallelism == ParallelismControl.PARALLEL)
        self.parallelism_dynamic.setChecked(pref.parallelism == ParallelismControl.DYNAMIC)

        self.parallelism_serial.toggled.connect(self.update_preferences)
        self.parallelism_parallel.toggled.connect(self.update_preferences)
        self.parallelism_dynamic.toggled.connect(self.update_preferences)

        self.update_preferences()

    def update_preferences(self):
        pref = get_pref()
        self.parallelism_parallel.setText(f"Parallel ({pref.processes})")
        self.parallelism_parallel.setToolTip(f"Run a fixed number of tests ({pref.processes}) in parallel.")
        if self.parallelism_serial.isChecked():
            pref.parallelism = ParallelismControl.SERIAL
        elif self.parallelism_parallel.isChecked():
            pref.parallelism = ParallelismControl.PARALLEL
        elif self.parallelism_dynamic.isChecked():
            pref.parallelism = ParallelismControl.DYNAMIC

    def get_selection(self) -> ParallelismControl:
        if self.parallelism_serial.isChecked():
            return ParallelismControl.SERIAL
        elif self.parallelism_parallel.isChecked():
            return ParallelismControl.PARALLEL
        elif self.parallelism_dynamic.isChecked():
            return ParallelismControl.DYNAMIC
        else:
            return ParallelismControl.SERIAL
