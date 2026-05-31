"""Tests for :mod:`pytest_fly.colors` — verify the color palette is well-formed."""

from PySide6.QtGui import QColor

from pytest_fly import colors
from pytest_fly.interfaces import PytestRunnerState

_SCALAR_COLOR_NAMES = [
    "GRID_LINE_COLOR",
    "COVERAGE_LINE_COLOR",
    "COVERAGE_FILL_COLOR",
    "CPU_LINE_COLOR",
    "MEMORY_LINE_COLOR",
    "DISK_READ_COLOR",
    "DISK_WRITE_COLOR",
    "NET_SENT_COLOR",
    "NET_RECV_COLOR",
]


def test_bar_colors_cover_every_state(app):
    """BAR_COLORS has a valid QColor for every runner state."""
    assert set(colors.BAR_COLORS) == set(PytestRunnerState)
    assert all(isinstance(color, QColor) and color.isValid() for color in colors.BAR_COLORS.values())


def test_table_colors_cover_every_state(app):
    """TABLE_COLORS has a valid QColor for every runner state."""
    assert set(colors.TABLE_COLORS) == set(PytestRunnerState)
    assert all(isinstance(color, QColor) and color.isValid() for color in colors.TABLE_COLORS.values())


def test_scalar_colors_are_valid_qcolors(app):
    """Each standalone chart/grid color constant is a valid QColor."""
    for name in _SCALAR_COLOR_NAMES:
        color = getattr(colors, name)
        assert isinstance(color, QColor), name
        assert color.isValid(), name
