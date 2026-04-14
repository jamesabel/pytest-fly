from PySide6.QtWidgets import QPushButton, QSizePolicy


class ControlButton(QPushButton):
    """Fixed-size push button used in the Run tab control panel."""

    def __init__(self, parent, text: str, enabled: bool):
        super().__init__(parent)
        self.setText(text)
        self.setEnabled(enabled)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.adjustSize()
