from PySide6.QtWidgets import QMainWindow, QApplication, QTabWidget

from .gui_util import get_font
from .home import Home
from .tests import Tests
from .history import History
from .configuration import Configuration
from .about import About
from ..preferences import get_pref
from ...__version__ import application_name


# class HomeTab(QWidget):
#     _update_signal = Signal()
#
#     def __init__(self):
#         super().__init__()
#
#         self.setWindowTitle(application_name)
#
#         # restore window position and size
#         pref = get_pref()
#         screen = QApplication.primaryScreen()
#         available_geometry = screen.availableGeometry()
#         x = min(pref.window_x, available_geometry.width() - 1)
#         y = min(pref.window_y, available_geometry.height() - 1)
#         width = min(pref.window_width, available_geometry.width())
#         height = min(pref.window_height, available_geometry.height())
#         splits = [int(value) for value in get_splits().get()]
#         if x > 0 and y > 0 and width > 0 and height > 0 and splits is not None:
#             self.setGeometry(x, y, width, height)
#             # self.central_window.set_sizes(splits)
#
#         # start file watcher
#         self.event_handler = DatabaseChangeHandler(self.request_update)
#         self.observer = Observer()
#         db_path = get_db_path()
#         self.observer.schedule(self.event_handler, path=str(db_path.parent), recursive=False)  # watchdog watches a directory
#         self.observer.start()
#         self._update_signal.connect(self.update_plot)
#
#         self.periodic_updater = PeriodicUpdater(self.request_update)
#         self.periodic_updater.start()
#
#         self.request_update()
#
#     def request_update(self):
#         self._update_signal.emit()
#
#     def update_plot(self):
#         pref = get_pref()
#         run_infos = get_most_recent_run_info()
#         # self.central_window.update_window(run_infos)
#         csv_dump(run_infos, Path(pref.csv_dump_path))
#
#     def closeEvent(self, event):
#         pref = get_pref()
#
#         pref.window_x = self.x()
#         frame_height = self.frameGeometry().height() - self.geometry().height()
#         pref.window_y = self.y() + frame_height
#         pref.window_width = self.width()
#         pref.window_height = self.height()
#
#         sizes = [str(size) for size in self.central_window.get_sizes()]
#         get_splits().set(sizes)
#
#         self.observer.stop()
#         self.periodic_updater.request_stop()
#         self.observer.join()
#         self.periodic_updater.wait()
#
#         event.accept()


class FlyAppMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setFont(get_font())

        pref = get_pref()
        self.setGeometry(pref.window_x, pref.window_y, pref.window_width, pref.window_height)

        self.setWindowTitle(application_name)

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
        pref = get_pref()

        pref.window_x = self.x()
        frame_height = self.frameGeometry().height() - self.geometry().height()
        pref.window_y = self.y() + frame_height
        pref.window_width = self.width()
        pref.window_height = self.height()

        self.home.control_window.exit_request()

        event.accept()


def view_main():
    app = QApplication([])
    fly_app = FlyAppMainWindow()
    fly_app.show()
    app.exec()
