"""Failed tests pane — lists test names that have failed in the current run, with clipboard copy support."""

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout

from ...gui.gui_util import PlainTextWidget
from ...interfaces import PytestRunnerState
from ...tick_data import TickData


class FailedTestsWindow(QGroupBox):
    """Displays a list of failed test names with a button to copy them to the clipboard."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Failed Tests")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._failed_names: list[str] = []

        self._text_widget = PlainTextWidget(self, "(none)")
        layout.addWidget(self._text_widget)

        button_layout = QHBoxLayout()
        self._copy_button = QPushButton("Copy to Clipboard")
        self._copy_button.setEnabled(False)
        self._copy_button.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(self._copy_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def update_tick(self, tick: TickData):
        """Rebuild the failed test list from pre-computed tick data."""
        failed_names = [test_name for test_name, run_state in tick.run_states.items() if run_state.get_state() == PytestRunnerState.FAIL]

        if failed_names != self._failed_names:
            self._failed_names = failed_names
            if failed_names:
                self._text_widget.set_text("\n".join(failed_names))
                self._copy_button.setEnabled(True)
            else:
                self._text_widget.set_text("(none)")
                self._copy_button.setEnabled(False)

    def _copy_to_clipboard(self):
        """Copy the failed test names to the system clipboard."""
        from PySide6.QtWidgets import QApplication

        if self._failed_names:
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(self._failed_names))
