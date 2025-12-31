from PySide6.QtWidgets import QGroupBox

from ...interfaces import PytestProcessInfo


class GraphTab(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Graph View")

    def update_pytest_process_info(self, pytest_process_infos: list[PytestProcessInfo]) -> None:
        pass
