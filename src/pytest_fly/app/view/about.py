from dataclasses import asdict

import humanize
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout

from .gui_util import PlainTextWidget
from ..project_info import get_project_info
from ..platform_info import get_platform_info


class About(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("About")

        text_lines = []
        for key, value in asdict(get_project_info()).items():
            text_lines.append(f"{key}: {value}")
        text_lines.append("")

        for key, value in get_platform_info().items():
            if any([descriptor in key.lower() for descriptor in ["cache", "memory"]]):
                text_lines.append(f"{key}: {humanize.naturalsize(value)}")
            else:
                text_lines.append(f"{key}: {value}")

        about_box = PlainTextWidget()
        about_box.set_text("\n".join(text_lines))

        horizontal_layout = QHBoxLayout()
        horizontal_layout.addWidget(about_box)
        horizontal_layout.addStretch()

        vertical_layout = QVBoxLayout()
        self.setLayout(vertical_layout)
        vertical_layout.addLayout(horizontal_layout)
        vertical_layout.addStretch()
