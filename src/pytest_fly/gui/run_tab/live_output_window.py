"""Live output pane — shows the streaming pytest stdout/stderr of a currently-running test."""

import time
from pathlib import Path

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QSizePolicy, QVBoxLayout
from typeguard import typechecked

from ...interfaces import PytestRunnerState
from ...pytest_runner.live_output import read_live_output
from ...tick_data import TickData
from ..gui_util import format_runtime, resolve_test_output

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
        # When set, the pane is "pinned" to a failed test's captured output, overriding the
        # normal running-test stream until the selection is cleared.
        self._pinned_failed_name: str | None = None
        self._latest_tick: TickData | None = None
        # Set on unpin to force the running-test selector to rebuild on the next tick, even
        # if the running set is unchanged (it must be re-enabled and repopulated after pinning).
        self._force_selector_rebuild: bool = False

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

        status_row = QHBoxLayout()
        self._elapsed_label = QLabel("")
        status_row.addWidget(self._elapsed_label)
        self._status_separator = QLabel("|")
        self._status_separator.setEnabled(False)
        status_row.addWidget(self._status_separator)
        self._last_pass_label = QLabel("")
        status_row.addWidget(self._last_pass_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("")
        self._progress_bar.setEnabled(False)
        layout.addWidget(self._progress_bar)

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setUndoRedoEnabled(False)
        self._text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._text_view.setMaximumBlockCount(_MAX_LINE_BLOCKS)
        self._text_view.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        layout.addWidget(self._text_view)

    def set_pinned_failed_test(self, name: str | None) -> None:
        """Pin the pane to a failed test's captured output (or unpin and resume live streaming).

        :param name: Failed test node id to display, or ``None`` to revert to the running-test stream.
        """
        self._pinned_failed_name = name
        self._last_text = ""  # force a refresh on the next render

        if name is not None:
            self.setTitle(f"Failed Test Output — {name}")
            self._test_selector.setEnabled(False)
            self._follow_tail_checkbox.setEnabled(False)
            self._elapsed_label.setText(f"Showing failed test: {name}")
            self._last_pass_label.setText("")
            self._status_separator.setVisible(False)
            self._progress_bar.setEnabled(False)
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("")
            self._render_pinned()
        else:
            self.setTitle("Live Output")
            self._follow_tail_checkbox.setEnabled(True)
            # Force the running-test selector to rebuild on the next tick so it is re-enabled
            # and repopulated even when the running set has not changed since pinning.
            self._force_selector_rebuild = True
            self._text_view.clear()
            if self._latest_tick is not None:
                self.update_tick(self._latest_tick)

    def _render_pinned(self) -> None:
        """Render the pinned failed test's captured output into the text view (top-aligned)."""
        name = self._pinned_failed_name
        if name is None:
            return
        infos = self._latest_tick.infos_by_name.get(name, []) if self._latest_tick is not None else []
        output = resolve_test_output(infos, self._data_dir, name)
        if output != self._last_text:
            self._text_view.setPlainText(output)
            self._last_text = output
            self._text_view.verticalScrollBar().setValue(0)  # failures sit at/near the top of pytest output

    def update_tick(self, tick: TickData) -> None:
        """Refresh combo-box membership and the live text for the selected test."""
        self._latest_tick = tick

        # When pinned to a failed test, show its captured output and skip the running-test flow.
        if self._pinned_failed_name is not None:
            self._render_pinned()
            return

        running_names = [name for name, run_state in tick.run_states.items() if run_state.get_state() == PytestRunnerState.RUNNING]

        if running_names != self._running_names or self._force_selector_rebuild:
            self._force_selector_rebuild = False
            self._rebuild_selector(running_names)

        if self._selected_name is None:
            if self._last_text:
                self._text_view.clear()
                self._last_text = ""
            self._elapsed_label.setText("")
            self._last_pass_label.setText("")
            self._status_separator.setVisible(False)
            self._progress_bar.setEnabled(False)
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("")
            return

        self._update_status(tick)

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

    def _update_status(self, tick: TickData) -> None:
        """Update elapsed time, last-successful-run, and the progress bar (100% = last successful runtime)."""
        start_time: float | None = None
        for info in tick.infos_by_name.get(self._selected_name, []):
            if info.pid is not None:
                start_time = info.time_stamp
                break
        elapsed = time.time() - start_time if start_time is not None else None

        last_pass = tick.last_pass_data.get(self._selected_name)
        last_pass_duration = last_pass[1] if last_pass is not None else None

        self._status_separator.setVisible(True)

        if elapsed is None:
            self._elapsed_label.setText("Elapsed: (starting)")
        else:
            self._elapsed_label.setText(f"Elapsed: {format_runtime(elapsed)}")

        if last_pass_duration is None:
            self._last_pass_label.setText("Last successful run: (none)")
        else:
            self._last_pass_label.setText(f"Last successful run: {format_runtime(last_pass_duration)}")

        if elapsed is not None and last_pass_duration is not None and last_pass_duration > 0:
            percent = int(round(elapsed / last_pass_duration * 100.0))
            self._progress_bar.setEnabled(True)
            self._progress_bar.setValue(min(100, max(0, percent)))
            self._progress_bar.setFormat(f"{percent}%")
        else:
            self._progress_bar.setEnabled(False)
            self._progress_bar.setValue(0)
            self._progress_bar.setFormat("")

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
