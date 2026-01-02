from functools import lru_cache, cache

from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtCore import QSize, Qt


@cache
def get_font() -> QFont:
    # monospace font
    font = QFont("Monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setBold(True)
    assert font.styleHint() == QFont.StyleHint.Monospace
    assert font.fixedPitch()
    return font


@lru_cache(maxsize=1000)
def get_text_dimensions(text: str, pad: bool = False) -> QSize:
    """
    Determine the dimensions of the provided text

    :param text: The text to measure
    :param pad: Whether to add padding to the text
    :return: The size of the text
    """
    font = get_font()
    metrics = QFontMetrics(font)
    text_size = metrics.size(0, text)  # Get the size of the text (QSize)
    if pad:
        single_character_size = metrics.size(0, "X")
        text_size.setWidth(text_size.width() + single_character_size.width())
        text_size.setHeight(text_size.height() + single_character_size.height())
    return text_size


class PlainTextWidget(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setReadOnly(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_text(self, text: str):
        self.setPlainText(text)
        # Tell layouts the size hint changed
        self.updateGeometry()
        self.adjustSize()
