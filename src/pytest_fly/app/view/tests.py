from PySide6.QtWidgets import QGroupBox, QVBoxLayout

from ..test_list import get_tests
from .gui_util import PlainTextWidget


class Tests(QGroupBox):

    def __init__(self):
        super().__init__()
        self.setTitle("Tests")
        layout = QVBoxLayout()
        self.test_widget = PlainTextWidget()
        layout.addWidget(self.test_widget)
        self.setLayout(layout)
        layout.addStretch()
        self.display_tests()

    def display_tests(self):
        tests = get_tests()
        self.test_widget.set_text("\n".join(tests))
