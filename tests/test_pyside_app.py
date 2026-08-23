"""A small PySide6 application, tested the way a GUI program under test would be.

pytest-fly runs this ``tests/`` tree as its own program under test, so this module is a
stand-in for a real Qt PUT: it creates a QApplication and widgets inside a pytest-fly test
child, drives them with ``qtbot``, and checks that pytest-fly's own GUI package has *not*
been pre-loaded into that child — a PUT must get a clean process, with only the Qt it
imports itself.
"""

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from pytest_fly.const import PYTEST_FLY_FAULTHANDLER_STRING


class CounterWindow(QMainWindow):
    """A window with a label and two buttons that count up and reset."""

    count_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Counter")
        self._count = 0

        self.label = QLabel(self._label_text())
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.increment_button = QPushButton("Increment")
        self.increment_button.clicked.connect(self.increment)

        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset)
        self.reset_button.setEnabled(False)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.label)
        layout.addWidget(self.increment_button)
        layout.addWidget(self.reset_button)
        self.setCentralWidget(central)

    @property
    def count(self) -> int:
        return self._count

    def increment(self) -> None:
        self._set_count(self._count + 1)

    def reset(self) -> None:
        self._set_count(0)

    def _set_count(self, value: int) -> None:
        self._count = value
        self.label.setText(self._label_text())
        self.reset_button.setEnabled(value != 0)
        self.count_changed.emit(value)

    def _label_text(self) -> str:
        return f"Count: {self._count}"


def test_click_increments(qtbot):
    window = CounterWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.count == 0
    assert window.label.text() == "Count: 0"
    assert not window.reset_button.isEnabled()

    qtbot.mouseClick(window.increment_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.increment_button, Qt.MouseButton.LeftButton)

    assert window.count == 2
    assert window.label.text() == "Count: 2"
    assert window.reset_button.isEnabled()


def test_reset_clears_and_disables(qtbot):
    window = CounterWindow()
    qtbot.addWidget(window)
    window.increment()
    window.increment()

    qtbot.mouseClick(window.reset_button, Qt.MouseButton.LeftButton)

    assert window.count == 0
    assert window.label.text() == "Count: 0"
    assert not window.reset_button.isEnabled()


def test_count_changed_signal(qtbot):
    window = CounterWindow()
    qtbot.addWidget(window)

    with qtbot.waitSignal(window.count_changed, timeout=1000) as blocker:
        qtbot.mouseClick(window.increment_button, Qt.MouseButton.LeftButton)

    assert blocker.args == [1]


def test_pytest_fly_gui_not_preloaded_into_put_process():
    """Inside a pytest-fly test child, only the PUT's own Qt is present — not pytest-fly's GUI.

    pytest-fly exports PYTEST_FLY_FAULTHANDLER to every child it spawns, so its presence
    identifies this process as a child. Under a plain ``pytest tests/`` run the suite's own
    GUI tests legitimately import ``pytest_fly.gui``, so the check is skipped there.
    """
    if PYTEST_FLY_FAULTHANDLER_STRING not in os.environ:
        return  # not running as a pytest-fly child
    preloaded = sorted(m for m in sys.modules if m.startswith("pytest_fly.gui"))
    assert preloaded == [], f"pytest-fly's GUI package leaked into the program-under-test process: {preloaded}"
