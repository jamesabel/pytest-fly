"""Log tab — live view of pytest-fly's own application log.

By default (Verbose off) only *notable* records are shown: run events tagged with
:data:`~pytest_fly.logger.EVENT_EXTRA` — admission-gate deferrals, resource-guard
and force-stop interventions, worker-pool resizes — plus every warning and error.
Verbose shows all INFO+ records.  Each line is prefixed with the record's
date/time.  Records are buffered by a :class:`~pytest_fly.logger.GuiLogHandler`
(emitted from any thread) and drained into the view on the GUI refresh tick; a
bounded history of recent records is kept so toggling Verbose can rebuild the
view retroactively.

The Verbose and Follow-tail selections persist across sessions, and the line
limit is configurable in the Configuration tab.
"""

import logging
from collections import deque

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ...logger import GuiLogRecord, install_gui_log_handler
from ...preferences import get_pref


class LogTab(QWidget):
    """Displays the application's log lines as they arrive, with an event/verbose filter."""

    def __init__(self):
        super().__init__()

        self._handler = install_gui_log_handler()

        pref = get_pref()
        self._line_limit = max(1, int(pref.log_tab_line_limit))
        # Recent records (filtered *at display time*), so toggling Verbose can rebuild the
        # view with history included. Bounded to the same limit as the text view.
        self._history: deque[GuiLogRecord] = deque(maxlen=self._line_limit)

        layout = QVBoxLayout()
        self.setLayout(layout)

        top_row = QHBoxLayout()
        self._verbose_checkbox = QCheckBox("Verbose")
        self._verbose_checkbox.setToolTip(
            "Unchecked: show only notable run events (admission gate, resource guard, force stops, ...)\nplus all warnings and errors. Checked: show every log line (INFO and above)."
        )
        self._verbose_checkbox.setChecked(bool(pref.log_tab_verbose))
        self._verbose_checkbox.toggled.connect(self._on_verbose_toggled)
        top_row.addWidget(self._verbose_checkbox)

        self._follow_tail_checkbox = QCheckBox("Follow tail")
        self._follow_tail_checkbox.setToolTip("Keep the view scrolled to the newest log line. Scrolling up turns this off automatically; re-check to resume following.")
        self._follow_tail_checkbox.setChecked(bool(pref.log_tab_follow_tail))
        self._follow_tail_checkbox.toggled.connect(self._on_follow_tail_toggled)
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
        self._text_view.setMaximumBlockCount(self._line_limit)
        self._text_view.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        layout.addWidget(self._text_view)

    def update_tick(self) -> None:
        """Drain newly buffered log records into the view (called on the GUI refresh tick)."""
        self._apply_line_limit_if_changed()
        records = self._handler.drain()
        if not records:
            return
        self._history.extend(records)
        visible_lines = [record.line for record in records if self._is_visible(record)]
        if not visible_lines:
            return
        self._text_view.appendPlainText("\n".join(visible_lines))
        self._scroll_to_tail_if_following()

    def _is_visible(self, record: GuiLogRecord) -> bool:
        """A record shows when Verbose is on, or it is a tagged run event, or a warning/error."""
        return self._verbose_checkbox.isChecked() or record.event or record.levelno >= logging.WARNING

    def _apply_line_limit_if_changed(self) -> None:
        """Adopt a changed Configuration-tab line limit: resize the history and the view."""
        limit = max(1, int(get_pref().log_tab_line_limit))
        if limit == self._line_limit:
            return
        self._line_limit = limit
        self._history = deque(self._history, maxlen=limit)
        self._text_view.setMaximumBlockCount(limit)
        self._rebuild_view()

    def _rebuild_view(self) -> None:
        """Re-render the whole view from history with the active filter."""
        visible_lines = [record.line for record in self._history if self._is_visible(record)]
        self._text_view.setPlainText("\n".join(visible_lines))
        self._scroll_to_tail_if_following()

    def _scroll_to_tail_if_following(self) -> None:
        if self._follow_tail_checkbox.isChecked():
            scrollbar = self._text_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_verbose_toggled(self, _checked: bool) -> None:
        """Persist the Verbose selection and re-render history under the new filter."""
        get_pref().log_tab_verbose = self._verbose_checkbox.isChecked()
        self._rebuild_view()

    def _on_follow_tail_toggled(self, _checked: bool) -> None:
        """Persist the Follow-tail selection (including the automatic off on manual scroll)."""
        get_pref().log_tab_follow_tail = self._follow_tail_checkbox.isChecked()
        self._scroll_to_tail_if_following()

    def _text_view_clear(self) -> None:
        """Clear the display and the retained history (the underlying log file is untouched)."""
        self._history.clear()
        self._text_view.clear()

    def _on_scroll_changed(self, value: int) -> None:
        """If the user manually scrolls away from the bottom, disable follow-tail."""
        if not self._follow_tail_checkbox.isChecked():
            return
        scrollbar = self._text_view.verticalScrollBar()
        if value < scrollbar.maximum():
            self._follow_tail_checkbox.setChecked(False)
