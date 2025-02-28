from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QScrollArea, QWidget

from ..test_list import get_tests
from .gui_util import PlainTextWidget


class ListOfTests(QGroupBox):

    def __init__(self):
        super().__init__()
        self.setTitle("Tests")
        layout = QVBoxLayout()

        # Create a scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # Create a widget to hold the content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        self.test_widget = PlainTextWidget()
        content_layout.addWidget(self.test_widget)
        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        self.setLayout(layout)

        tests = get_tests()
        self.test_widget.set_text("\n".join(tests))
