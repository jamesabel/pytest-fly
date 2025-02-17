from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout

from .gui_util import PlainTextWidget
from ..project_info import get_project_info


class About(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("About")

        project_info = get_project_info()

        about_box = PlainTextWidget()
        about_box.set_text(str(project_info))

        horizontal_layout = QHBoxLayout()
        horizontal_layout.addWidget(about_box)
        horizontal_layout.addStretch()

        vertical_layout = QVBoxLayout()
        self.setLayout(vertical_layout)
        vertical_layout.addLayout(horizontal_layout)
        vertical_layout.addStretch()
