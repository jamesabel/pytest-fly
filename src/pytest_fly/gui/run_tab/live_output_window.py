"""Live output pane — shows the streaming pytest stdout/stderr of a currently-running test."""

from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QPlainTextEdit, QSizePolicy, QVBoxLayout
from typeguard import typechecked

from ...interfaces import PytestRunnerState
from ...pytest_runner.live_output import read_live_output
from ...tick_data import TickData

_NO_TESTS_RUNNING_PLACEHOLDER = "(no tests running)"
_MAX_LINE_BLOCKS = 5000  # QPlainTextEdit max line count — bounds memory on very chatty tests


class LiveOutputWindow(QGroupBox):
    """Displays live pytest output for a selectable running test."""

    @typechecked()
    def __init__(self, parent, data_dir: Path):
        super().__init__(parent)
        self.setTitle("Live Output")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._data_dir = data_dir
        self._running_names: list[str] = []
        self._selected_name: str | None = None
        self._last_text: str = ""

        layout = QVBoxLayout()
        self.setLayout(layout)

        top_row = QHBoxLayout()
        self._test_selector = QComboBox()
        self._test_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._test_selector.addItem(_NO_TESTS_RUNNING_PLACEHOLDER)
        self._test_selector.setEnabled(False)
        self._test_selector.currentIndexChanged.connect(self._on_selector_changed)
        top_row.addWidget(self._test_selector)

        self._follow_tail_checkbox = QCheckBox("Follow tail")
        self._follow_tail_checkbox.setChecked(True)
        top_row.addWidget(self._follow_tail_checkbox)
        layout.addLayout(top_row)

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setUndoRedoEnabled(False)
        self._text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._text_view.setMaximumBlockCount(_MAX_LINE_BLOCKS)
        self._text_view.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        layout.addWidget(self._text_view)

    def update_tick(self, tick: TickData) -> None:
        """Refresh combo-box membership and the live text for the selected test."""
        running_names = [name for name, run_state in tick.run_states.items() if run_state.get_state() == PytestRunnerState.RUNNING]

        if running_names != self._running_names:
            self._rebuild_selector(running_names)

        if self._selected_name is None:
            if self._last_text:
                self._text_view.clear()
                self._last_text = ""
            return

        live_text = read_live_output(self._data_dir, self._selected_name)
        if live_text is None:
            live_text = ""
        if live_text != self._last_text:
            self._text_view.setPlainText(live_text)
            self._last_text = live_text
            if self._follow_tail_checkbox.isChecked():
                scrollbar = self._text_view.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

    def _rebuild_selector(self, running_names: list[str]) -> None:
        """Rebuild the combo-box while preserving the selected test if still running."""
        previous_selection = self._selected_name
        self._running_names = running_names
        self._test_selector.blockSignals(True)
        self._test_selector.clear()
        if running_names:
            self._test_selector.addItems(running_names)
            self._test_selector.setEnabled(True)
            if previous_selection in running_names:
                self._test_selector.setCurrentIndex(running_names.index(previous_selection))
                self._selected_name = previous_selection
            else:
                self._test_selector.setCurrentIndex(0)
                self._selected_name = running_names[0]
                self._last_text = ""
                self._text_view.clear()
        else:
            self._test_selector.addItem(_NO_TESTS_RUNNING_PLACEHOLDER)
            self._test_selector.setEnabled(False)
            self._selected_name = None
        self._test_selector.blockSignals(False)

    def _on_selector_changed(self, index: int) -> None:
        """User picked a different running test — switch the text view."""
        if 0 <= index < len(self._running_names):
            self._selected_name = self._running_names[index]
            self._last_text = ""
            self._text_view.clear()

    def _on_scroll_changed(self, value: int) -> None:
        """If the user manually scrolls away from the bottom, disable follow-tail."""
        if not self._follow_tail_checkbox.isChecked():
            return
        scrollbar = self._text_view.verticalScrollBar()
        if value < scrollbar.maximum():
            self._follow_tail_checkbox.setChecked(False)
