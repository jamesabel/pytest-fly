from pathlib import Path

from ismain import is_main

from .visualization import visualize


def main():
    visualize(Path("temp", "ptest-fly.png"))  # todo: make output file a command line argument


if is_main():
    main()
