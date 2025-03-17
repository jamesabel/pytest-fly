from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QRadioButton, QButtonGroup
from ....preferences import get_pref, RunMode


class RunModeControlBox(QGroupBox):

    def __init__(self, parent):
        super().__init__("Run Mode", parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.run_mode_group = QButtonGroup(self)
        self.resume_restart = QRadioButton("Restart")
        self.resume_restart.setToolTip("Always rerun all tests from scratch.")
        self.resume_resume = QRadioButton("Resume")
        self.resume_resume.setToolTip("Resume test run. Only run tests\nthat either failed or were not run.")
        self.resume_check = QRadioButton("Check")
        self.resume_check.setToolTip("Check the version of the program under test.\nIf the version has not changed, resume the test run.\nIf the version has changed, restart the test run.")

        self.run_mode_group.addButton(self.resume_restart)
        self.run_mode_group.addButton(self.resume_resume)
        self.run_mode_group.addButton(self.resume_check)

        layout.addWidget(self.resume_restart)
        layout.addWidget(self.resume_resume)
        layout.addWidget(self.resume_check)

        pref = get_pref()
        self.resume_restart.setChecked(pref.run_mode == RunMode.RESTART)
        self.resume_resume.setChecked(pref.run_mode == RunMode.RESUME)
        self.resume_check.setChecked(pref.run_mode == RunMode.CHECK)

        self.resume_restart.toggled.connect(self.update_preferences)
        self.resume_resume.toggled.connect(self.update_preferences)
        self.resume_check.toggled.connect(self.update_preferences)

    def update_preferences(self):
        pref = get_pref()
        if self.resume_restart.isChecked():
            pref.run_mode = RunMode.RESTART
        elif self.resume_resume.isChecked():
            pref.run_mode = RunMode.RESUME
        elif self.resume_check.isChecked():
            pref.run_mode = RunMode.CHECK
