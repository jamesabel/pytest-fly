from PySide6.QtWidgets import QWidget


class Configuration(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Configuration")  # Configuration seems like a good name, but could be called Preferences
