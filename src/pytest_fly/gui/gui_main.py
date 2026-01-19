# python
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QApplication,
    QTabWidget,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import QCoreApplication, QRect, QTimer, Qt
from typeguard import typechecked

from ..db import PytestProcessInfoDB
from ..logger import get_logger
from ..gui.configuration_tab.configuration import Configuration
from ..gui.about_tab.about import About
from ..preferences import get_pref
from ..__version__ import application_name
from .gui_util import get_font, get_text_dimensions
from .run_tab import RunTab
from .table_tab import TableTab
from .graph_tab import GraphTab


log = get_logger()


class FlyAppMainWindow(QMainWindow):
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

        super().__init__()

        # set monospace font
        font = get_font()
        self.setFont(font)

        # ensure monospace font is used
        space_dimension = get_text_dimensions(" ")
        wide_character_dimension = get_text_dimensions("X")
        if space_dimension.width() != wide_character_dimension.width():
            log.warning(f"monospace font not used (font={font})")

        # restore window size and position
        pref = get_pref()
        # ensure window is not off the screen
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        restore_rect = QRect(int(float(pref.window_x)), int(float(pref.window_y)), int(float(pref.window_width)), int(float(pref.window_height)))
        if not screen_geometry.contains(restore_rect):
            padding = 0.1  # when resizing, leave a little padding on each side
            screen_width = screen_geometry.width()
            screen_height = screen_geometry.height()
            restore_rect = QRect(int(padding * screen_width), int(padding * screen_height), int((1.0 - 2 * padding) * screen_width), int((1.0 - 2 * padding) * screen_height))
            log.info(f"window is off the screen, moving to {restore_rect=}")
        self.setGeometry(restore_rect)

        self.setWindowTitle(application_name)

        # add tab windows
        self.tab_widget = QTabWidget()
        # ensure the tab widget expands but does not force the main window to grow
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.run_tab = RunTab(self, self.data_dir)
        self.graph_tab = GraphTab()
        self.table_tab = TableTab()
        self.configuration = Configuration()
        self.about = About(self)
        self.tab_widget.addTab(self.run_tab, "Run")
        self.tab_widget.addTab(self.graph_tab, "Graph")
        self.tab_widget.addTab(self.table_tab, "Table")
        self.tab_widget.addTab(self.configuration, "Configuration")
        self.tab_widget.addTab(self.about, "About")

        # Wrap the tab widget in a scroll area so that very tall tab contents produce scrollbars
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        # QScrollArea takes ownership / reparents the widget
        self.scroll_area.setWidget(self.tab_widget)

        self.setCentralWidget(self.scroll_area)

        # timer for periodic updates
        self.timer = QTimer(self, interval=int(round(pref.refresh_rate * 1000)))
        self.timer.timeout.connect(self.update_pytest_process_info)
        self.timer.start()

    def constrain_to_screen(self):
        """
        Ensure the main window size and position stay within the primary screen's available geometry.
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()

        # clamp size
        new_width = min(self.width(), avail.width())
        new_height = min(self.height(), avail.height())
        if (new_width, new_height) != (self.width(), self.height()):
            self.resize(new_width, new_height)

        # clamp position
        new_x = min(max(self.x(), avail.left()), avail.right() - self.width())
        new_y = min(max(self.y(), avail.top()), avail.bottom() - self.height())
        if (new_x, new_y) != (self.x(), self.y()):
            self.move(new_x, new_y)

        # ensure maximums follow the screen in case of DPI/monitor changes
        self.setMaximumSize(avail.width(), avail.height())

    def reset(self):
        self.table_tab.reset()
        # after resetting potentially large content, make sure window stays on-screen
        self.constrain_to_screen()

    def closeEvent(self, event, /):

        log.info(f"{__class__.__name__}.closeEvent() - entering")

        pref = get_pref()

        # save window size and position using frameGeometry (includes window frame)
        frame = self.frameGeometry()
        pref.window_x = frame.x()
        pref.window_y = frame.y()
        pref.window_width = frame.width()
        pref.window_height = frame.height()

        if (pytest_runner := self.run_tab.control_window.pytest_runner) is not None and pytest_runner.is_running():
            pytest_runner.stop()
            QCoreApplication.processEvents()
            pytest_runner.join(30.0)

        event.accept()

    def moveEvent(self, event):
        super().moveEvent(event)
        # keep the window inside the visible screen when moved
        self.constrain_to_screen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # keep the window inside the visible screen when resized
        self.constrain_to_screen()

    def update_pytest_process_info(self):
        """
        Timer event handler to update the GUI.
        """
        with PytestProcessInfoDB(self.data_dir) as db:
            process_infos = db.query(self.run_tab.control_window.run_guid)
            self.graph_tab.update_pytest_process_info(process_infos)
            self.table_tab.update_pytest_process_info(process_infos)
            self.run_tab.update_pytest_process_info(process_infos)
        # content updates may change preferred sizes; ensure the main window remains visible
        self.constrain_to_screen()


@typechecked()
def fly_main(data_dir: Path):
    """
    Main function to start the GUI application.
    """

    app = QApplication([])
    fly_app = FlyAppMainWindow(data_dir)
    fly_app.show()
    app.exec()
