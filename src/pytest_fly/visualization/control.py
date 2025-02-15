from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QPushButton


class ControlWindow(QGroupBox):
    def __init__(self):
        super().__init__()
        self.setTitle("Control")
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.run_button = QPushButton("Run")
        layout.addWidget(self.run_button)
        layout.addStretch()
