import multiprocessing

from PySide6.QtWidgets import QMainWindow, QApplication, QTabWidget
from PySide6.QtCore import QCoreApplication

from .gui_util import get_font, get_text_dimensions
from ..logging import get_logger
from .home import Home
from .tests import Tests
from .history import History
from .configuration import Configuration
from .about import About
from ..preferences import get_pref
from ...__version__ import application_name

log = get_logger()


class FlyAppMainWindow(QMainWindow):
    def __init__(self):
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
        self.setGeometry(pref.window_x, pref.window_y, pref.window_width, pref.window_height)

        self.setWindowTitle(application_name)

        # add tab windows
        self.tab_widget = QTabWidget()
        self.home = Home(self)
        self.tests = Tests()
        self.history = History()
        self.configuration = Configuration()
        self.about = About()
        self.tab_widget.addTab(self.home, "Home")
        self.tab_widget.addTab(self.tests, "Tests")
        self.tab_widget.addTab(self.history, "History")
        self.tab_widget.addTab(self.configuration, "Configuration")
        self.tab_widget.addTab(self.about, "About")

        self.setCentralWidget(self.tab_widget)

    def closeEvent(self, event, /):

        log.info(f"{__class__.__name__}.closeEvent() - entering")

        pref = get_pref()

        pref.window_x = self.x()
        frame_height = self.frameGeometry().height() - self.geometry().height()
        pref.window_y = self.y() + frame_height
        pref.window_width = self.width()
        pref.window_height = self.height()

        if self.home.control_window.pytest_runner_worker is not None:
            log.info(f"{__class__.__name__}.closeEvent() - request_exit_signal.emit()")
            self.home.control_window.pytest_runner_worker.request_stop()
            QCoreApplication.processEvents()
            self.home.control_window.pytest_runner_worker.request_exit()
            QCoreApplication.processEvents()
            while self.home.control_window.pytest_runner_thread.isRunning():
                QCoreApplication.processEvents()
                log.info(f"{__class__.__name__}.closeEvent() - waiting for worker thread to finish")
                self.home.control_window.pytest_runner_thread.wait(1000)

        log.info(f"{__class__.__name__}.closeEvent() - doing event.accept()")

        event.accept()

        log.info(f"{__class__.__name__}.closeEvent() - exiting")


def fly_main():
    multiprocessing.set_start_method("spawn")  # may not be necessary
    app = QApplication([])
    fly_app = FlyAppMainWindow()
    fly_app.show()
    app.exec()
