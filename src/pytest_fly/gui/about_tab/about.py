"""About tab — shows project metadata and system/hardware information."""

from dataclasses import asdict
from pathlib import Path

import humanize
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from pytest_fly.gui.gui_util import PlainTextWidget
from pytest_fly.logger import get_log_directory
from pytest_fly.platform.platform_info import get_performance_core_count, get_platform_info
from pytest_fly.preferences import get_pref
from pytest_fly.put_version import detect_put_version

# Preferred display order for Program Under Test fields; any fields not listed
# here are appended in dataclass declaration order.
_PUT_FIELD_ORDER = ("name", "version", "author", "source", "git_describe", "git_sha", "git_branch", "git_dirty", "project_root")


class AboutDataWorker(QObject):
    """
    A worker that gets data for the About window in the background.
    """

    data_ready = Signal(str)

    def run(self):
        text_lines = []

        pref = get_pref()
        project_root = Path(pref.target_project_path).resolve() if pref.target_project_path else Path.cwd()
        put_info = detect_put_version(project_root)
        put_fields = asdict(put_info)
        text_lines.append("Program Under Test:")
        for key in _PUT_FIELD_ORDER:
            if key in put_fields:
                text_lines.append(f"    {key}: {put_fields.pop(key)}")
        for key, value in put_fields.items():
            text_lines.append(f"    {key}: {value}")
        text_lines.append("")

        for key, value in get_platform_info().items():
            key_string = " ".join([s.capitalize() for s in key.split("_")]).replace("Cpu", "CPU")
            if any([descriptor in key.lower() for descriptor in ["cache", "memory"]]):
                text_lines.append(f"{key_string}: {humanize.naturalsize(value) if isinstance(value, (int, float)) else value}")
            elif "freq" in key:
                text_lines.append(f"{key_string}: {value / 1000.0} GHz")
            else:
                text_lines.append(f"{key_string}: {value}")

        text_lines.append("")
        text_lines.append(f"log_directory: {get_log_directory()}")

        text_lines.append("")
        text_lines.append("Notes:")
        text_lines.append('"Logical" cores are also known as Virtual, Hyper-Threading, or SMT.')
        text_lines.append(f'The default number of test processes is the number of "performance" cores, in this case {get_performance_core_count()}.')

        self.data_ready.emit("\n".join(text_lines))


class About(QWidget):
    """
    A window that shows information about the project and the system.
    """

    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle("About")

        self.about_box = PlainTextWidget(parent, "Loading...")
        self.about_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        vertical_layout = QVBoxLayout()
        self.setLayout(vertical_layout)
        vertical_layout.addWidget(self.about_box)

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
