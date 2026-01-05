from PySide6.QtWidgets import QPushButton, QSizePolicy


class ControlButton(QPushButton):

    def __init__(self, parent, text: str, enabled: bool):
        super().__init__(parent)
        self.setText(text)
        self.setEnabled(enabled)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.adjustSize()
