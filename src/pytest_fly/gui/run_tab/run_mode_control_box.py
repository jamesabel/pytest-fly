from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QRadioButton, QButtonGroup
from pytest_fly.preferences import get_pref, RunMode


class RunModeControlBox(QGroupBox):

    def __init__(self, parent):
        super().__init__("Run Mode", parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.run_mode_group = QButtonGroup(self)
        self.run_mode_restart = QRadioButton("Restart")
        self.run_mode_restart.setToolTip("Always rerun all tests from scratch.")
        self.run_mode_resume = QRadioButton("Resume")
        self.run_mode_resume.setToolTip("Resume test run. Only run tests\nthat either failed or were not run.")

        self.run_mode_group.addButton(self.run_mode_restart)
        self.run_mode_group.addButton(self.run_mode_resume)

        layout.addWidget(self.run_mode_restart)
        layout.addWidget(self.run_mode_resume)

        pref = get_pref()
        self.run_mode_restart.setChecked(pref.run_mode == RunMode.RESTART)
        self.run_mode_resume.setChecked(pref.run_mode == RunMode.RESUME)

        self.run_mode_restart.toggled.connect(self.update_preferences)
        self.run_mode_resume.toggled.connect(self.update_preferences)

    def update_preferences(self):
        pref = get_pref()
        if self.run_mode_restart.isChecked():
            pref.run_mode = RunMode.RESTART
        elif self.run_mode_resume.isChecked():
            pref.run_mode = RunMode.RESUME
