from multiprocessing import Process
from pathlib import Path
import textwrap
import pytest

from ismain import is_main

from pytest_fly import visualize


class Visualize(Process):
    def run(self):
        visualize()


def generate_tests():
    # generate tests

    test_file_prefix = "fly_case"
    test_dir = Path("fly_demo")
    test_dir.mkdir(exist_ok=True, parents=True)
    print(f'writing demo tests to "{test_dir.resolve()}"')
    # delete any existing tests
    for test_file in test_dir.glob(f"{test_file_prefix}*.py"):
        test_file.unlink()
    groups = 3
    subgroups = 4
    for test_group in range(groups):
        test_case_file = Path(test_dir, f"{test_file_prefix}_{chr(test_group + ord('a'))}.py")
        with test_case_file.open("w") as f:
            f.write("import time\n")
            f.write("\n")
            for test_case in range(subgroups):
                test_number = test_group * subgroups + test_case
                test_code = textwrap.dedent(
                    f"""
                    def test_case_{test_number}():
                        time.sleep({test_number})    
                                                    
                    """
                )
                f.write(test_code)


def demo():

    generate_tests()

    # start realtime watcher GUI
    visualize = Visualize()
    visualize.start()

    # run tests
    pytest.main(["-v", "-n", "4"])  # -n auto for xdist to run on all available processors

    # visualize.kill()  # stop visualization


if is_main():
    demo()
