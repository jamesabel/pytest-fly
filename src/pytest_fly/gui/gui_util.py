from functools import lru_cache, cache

from PySide6.QtWidgets import QPlainTextEdit
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
    """
    A read-only text widget that displays plain text.
    """

    def __init__(self):
        super().__init__()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # disable scroll bars
        # self.setFont(get_font())
        self.setReadOnly(True)

    def set_text(self, text: str):
        text_dimensions = get_text_dimensions(text, True)
        self.setFixedSize(text_dimensions.width(), text_dimensions.height())
        self.setPlainText(text)
