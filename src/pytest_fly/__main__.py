from ismain import is_main

from .visualization import visualize_qt, visualize_textual


def main():
    if True:
        visualize_qt()
    else:
        visualize_textual()


if is_main():
    main()
