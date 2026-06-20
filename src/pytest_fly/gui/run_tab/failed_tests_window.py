"""Failed tests pane — lists test names that have failed in the current run, with clipboard copy and click-to-inspect support."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout

from ...interfaces import PytestRunnerState
from ...tick_data import TickData


class FailedTestsWindow(QGroupBox):
    """Displays a clickable list of failed test names, with a button to copy them to the clipboard.

    Selecting a test emits :attr:`failed_test_selected` so a sibling pane can show that test's
    captured output; clearing the selection (clicking the selected row again) emits ``None``.
    """

    # Emitted with the selected test name (str) or None when the selection is cleared.
    failed_test_selected = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setTitle("Failed Tests")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._failed_names: list[str] = []
        self._selected_name: str | None = None

        self._list_widget = QListWidget(self)
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        # Drive the toggle from the full click (mouse release) only — not from selection
        # changes (which fire on mouse press), so a click is a complete on/off toggle
        # rather than "pinned only while the button is held".
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list_widget)

        button_layout = QHBoxLayout()
        self._copy_button = QPushButton("Copy to Clipboard")
        self._copy_button.setEnabled(False)
        self._copy_button.clicked.connect(self._copy_to_clipboard)
        button_layout.addWidget(self._copy_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def update_tick(self, tick: TickData):
        """Rebuild the failed test list from pre-computed tick data, preserving selection by name."""
        failed_names = [test_name for test_name, run_state in tick.run_states.items() if run_state.get_state() == PytestRunnerState.FAIL]

        if failed_names == self._failed_names:
            return
        self._failed_names = failed_names

        # Rebuild the list without letting the intermediate clear/add churn emit selection signals.
        self._list_widget.blockSignals(True)
        self._list_widget.clear()
        for name in failed_names:
            self._list_widget.addItem(QListWidgetItem(name))
        # Re-select the previously selected test if it is still failing; otherwise drop the selection.
        restored = self._selected_name if self._selected_name in failed_names else None
        if restored is not None:
            self._list_widget.setCurrentRow(failed_names.index(restored))
        self._list_widget.blockSignals(False)

        self._copy_button.setEnabled(bool(failed_names))

        if restored != self._selected_name:
            self._selected_name = restored
            self.failed_test_selected.emit(restored)

    def _on_item_clicked(self, item: QListWidgetItem):
        """Toggle: clicking a test pins it; clicking the already-pinned test unpins it."""
        name = item.text()
        if name == self._selected_name:
            # Re-clicked the pinned test -> turn the inspect view off.
            self._selected_name = None
            self._list_widget.setCurrentRow(-1)  # clears both the current item and the selection
            self.failed_test_selected.emit(None)
        else:
            self._selected_name = name
            self.failed_test_selected.emit(name)

    def _copy_to_clipboard(self):
        """Copy the failed test names to the system clipboard."""
        from PySide6.QtWidgets import QApplication

        if self._failed_names:
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(self._failed_names))
