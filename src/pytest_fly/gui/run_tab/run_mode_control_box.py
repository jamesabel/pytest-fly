"""Radio-button group for selecting the run mode (Resume / Restart)."""

from PySide6.QtWidgets import QButtonGroup, QGroupBox, QRadioButton, QVBoxLayout

from pytest_fly.preferences import RunMode, get_pref


class RunModeControlBox(QGroupBox):
    """Radio-button group for selecting the run mode (Resume / Restart)."""

    def __init__(self, parent):
        super().__init__("Run Mode", parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        self.run_mode_group = QButtonGroup(self)
        self.run_mode_resume = QRadioButton("Resume")
        self.run_mode_resume.setToolTip("Resume test run. Only run tests that either failed or were not run.\nPUT-change handling is configured in the Configuration tab.")
        self.run_mode_restart = QRadioButton("Restart")
        self.run_mode_restart.setToolTip("Always rerun all tests from scratch.")

        self.run_mode_group.addButton(self.run_mode_resume)
        self.run_mode_group.addButton(self.run_mode_restart)

        layout.addWidget(self.run_mode_resume)
        layout.addWidget(self.run_mode_restart)

        pref = get_pref()
        self.run_mode_resume.setChecked(pref.run_mode in (RunMode.RESUME, RunMode.CHECK))
        self.run_mode_restart.setChecked(pref.run_mode == RunMode.RESTART)

        self.run_mode_resume.toggled.connect(self.update_preferences)
        self.run_mode_restart.toggled.connect(self.update_preferences)

    def update_preferences(self):
        """Sync the selected radio button back to user preferences."""
        pref = get_pref()
        if self.run_mode_restart.isChecked():
            pref.run_mode = RunMode.RESTART
        elif self.run_mode_resume.isChecked():
            pref.run_mode = RunMode.RESUME if pref.resume_skip_put_check else RunMode.CHECK
