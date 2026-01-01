from pathlib import Path
from pprint import pprint

from PySide6.QtWidgets import QMainWindow, QApplication, QTabWidget
from PySide6.QtCore import QCoreApplication, QRect, QTimer
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
        restore_rect = QRect(pref.window_x, pref.window_y, pref.window_width, pref.window_height)
        if not screen_geometry.contains(restore_rect):
            pref.window_x = 0
            pref.window_y = 0
            pref.window_width = pref.window_width if pref.window_width < screen_geometry.width() else screen_geometry.width()
            pref.window_height = pref.window_height if pref.window_height < screen_geometry.height() else screen_geometry.height()
            log.info(f"window is off the screen, moving to (0, 0) with width={pref.window_width} and height={pref.window_height}")
        self.setGeometry(pref.window_x, pref.window_y, pref.window_width, pref.window_height)

        self.setWindowTitle(application_name)

        # add tab windows
        self.tab_widget = QTabWidget()
        self.run_tab = RunTab(self, self.data_dir)
        self.graph_tab = GraphTab()
        self.table_tab = TableTab()
        self.configuration = Configuration()
        self.about = About()
        self.tab_widget.addTab(self.run_tab, "Run")
        self.tab_widget.addTab(self.graph_tab, "Graph")
        self.tab_widget.addTab(self.table_tab, "Table")
        self.tab_widget.addTab(self.configuration, "Configuration")
        self.tab_widget.addTab(self.about, "About")

        self.setCentralWidget(self.tab_widget)

        self.timer = QTimer(self, interval=int(round(pref.refresh_rate * 1000)))
        self.timer.timeout.connect(self.update_pytest_process_info)
        self.timer.start()

    def reset(self):
        self.table_tab.reset()

    def closeEvent(self, event, /):

        log.info(f"{__class__.__name__}.closeEvent() - entering")

        pref = get_pref()

        # save window size and position
        pref.window_x = self.x()
        frame_height = self.frameGeometry().height() - self.geometry().height()
        pref.window_y = self.y() + frame_height
        pref.window_width = self.width()
        pref.window_height = self.height()

        if (pytest_runner := self.run_tab.control_window.pytest_runner) is not None and pytest_runner.is_running():
            pytest_runner.stop()
            QCoreApplication.processEvents()
            pytest_runner.join(30.0)

        event.accept()

    def update_pytest_process_info(self):
        """
        Timer event handler to update the GUI.
        """
        with PytestProcessInfoDB(self.data_dir) as db:
            process_infos = db.query(self.run_tab.control_window.run_guid)
            self.graph_tab.update_pytest_process_info(process_infos)
            self.table_tab.update_pytest_process_info(process_infos)
            self.run_tab.control_window.update()


@typechecked()
def fly_main(data_dir: Path):
    """
    Main function to start the GUI application.
    """

    app = QApplication([])
    fly_app = FlyAppMainWindow(data_dir)
    fly_app.show()
    app.exec()
