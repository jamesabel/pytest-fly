"""Log tab — live view of pytest-fly's own application log.

Shows the events the application logger emits at INFO and above — run lifecycle,
admission-gate deferrals, resource-guard and stall-watchdog triggers — each line
prefixed with the record's date/time.  Records are buffered by a
:class:`~pytest_fly.logger.GuiLogHandler` (emitted from any thread) and drained
into the view on the GUI refresh tick.
"""

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ...logger import install_gui_log_handler

_MAX_LINE_BLOCKS = 10_000  # QPlainTextEdit max line count — bounds memory over a long session


class LogTab(QWidget):
    """Displays the application's log lines as they arrive."""

    def __init__(self):
        super().__init__()

        self._handler = install_gui_log_handler()

        layout = QVBoxLayout()
        self.setLayout(layout)

        top_row = QHBoxLayout()
        self._follow_tail_checkbox = QCheckBox("Follow tail")
        self._follow_tail_checkbox.setToolTip("Keep the view scrolled to the newest log line. Scrolling up turns this off automatically; re-check to resume following.")
        self._follow_tail_checkbox.setChecked(True)
        top_row.addWidget(self._follow_tail_checkbox)
        top_row.addStretch()
        self._clear_button = QPushButton("Clear")
        self._clear_button.setToolTip("Clear the log view. Only the display is cleared — the log file on disk is unaffected.")
        self._clear_button.clicked.connect(self._text_view_clear)
        top_row.addWidget(self._clear_button)
        layout.addLayout(top_row)

        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setUndoRedoEnabled(False)
        self._text_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._text_view.setMaximumBlockCount(_MAX_LINE_BLOCKS)
        self._text_view.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        layout.addWidget(self._text_view)

    def update_tick(self) -> None:
        """Drain newly buffered log lines into the view (called on the GUI refresh tick)."""
        lines = self._handler.drain()
        if not lines:
            return
        self._text_view.appendPlainText("\n".join(lines))
        if self._follow_tail_checkbox.isChecked():
            scrollbar = self._text_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _text_view_clear(self) -> None:
        """Clear the display (the underlying log file is untouched)."""
        self._text_view.clear()

    def _on_scroll_changed(self, value: int) -> None:
        """If the user manually scrolls away from the bottom, disable follow-tail."""
        if not self._follow_tail_checkbox.isChecked():
            return
        scrollbar = self._text_view.verticalScrollBar()
        if value < scrollbar.maximum():
            self._follow_tail_checkbox.setChecked(False)
