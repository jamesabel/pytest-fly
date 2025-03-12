from dataclasses import asdict
import humanize
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from .gui_util import PlainTextWidget
from ..project_info import get_project_info
from pytest_fly.common.platform_info import get_platform_info, get_performance_core_count


class AboutDataWorker(QObject):
    """
    A worker that gets data for the About window in the background.
    """

    data_ready = Signal(str)

    def run(self):
        text_lines = []
        for key, value in asdict(get_project_info()).items():
            text_lines.append(f"{key}: {value}")
        text_lines.append("")

        for key, value in get_platform_info().items():
            key_string = " ".join([s.capitalize() for s in key.split("_")]).replace("Cpu", "CPU")
            if any([descriptor in key.lower() for descriptor in ["cache", "memory"]]):
                text_lines.append(f"{key_string}: {humanize.naturalsize(value)}")
            elif "freq" in key:
                text_lines.append(f"{key_string}: {value / 1000.0} GHz")
            else:
                text_lines.append(f"{key_string}: {value}")

        text_lines.append("")
        text_lines.append("Notes:")
        text_lines.append('"Logical" cores are also known as Virtual, Hyper-Threading, or SMT.')
        text_lines.append(f'The default number of test processes is the number of "performance" cores, in this case {get_performance_core_count()}.')

        self.data_ready.emit("\n".join(text_lines))


class About(QWidget):
    """
    A window that shows information about the project and the system.
    """

    def __init__(self):
        super().__init__()

        self.setWindowTitle("About")

        self.about_box = PlainTextWidget()
        self.about_box.set_text("Loading...")

        horizontal_layout = QHBoxLayout()
        horizontal_layout.addWidget(self.about_box)
        horizontal_layout.addStretch()

        vertical_layout = QVBoxLayout()
        self.setLayout(vertical_layout)
        vertical_layout.addLayout(horizontal_layout)
        vertical_layout.addStretch()

        self.worker = AboutDataWorker()
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.worker.data_ready.connect(self.update_about_box)
        self.thread.started.connect(self.worker.run)
        self.thread.start()

    def update_about_box(self, text):
        """
        Update the About box with the given text.
        """
        self.about_box.set_text(text)
        self.thread.quit()
        self.thread.wait()
