from pytest_fly.gui.gui_util import get_text_dimensions


def test_get_font(app):
    # ensure that the font is monospaced
    number_of_characters = 100
    # pick strings that will not have the same width unless they are monospaced
    text_dimensions_spaces = get_text_dimensions(number_of_characters * " ")
    text_dimensions_dots = get_text_dimensions(number_of_characters * ".")
    text_dimensions_xs = get_text_dimensions(number_of_characters * "X")
    assert text_dimensions_spaces.width() == text_dimensions_xs.width()
    assert text_dimensions_dots.width() == text_dimensions_xs.width()
