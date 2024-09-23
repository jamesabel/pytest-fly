from ismain import is_main

from pytest_fly import visualize


def demo():
    visualize()
    # start realtime watcher GUI
    # run tests
    # shut down


if is_main():
    demo()
