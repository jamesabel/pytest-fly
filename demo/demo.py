import textwrap
from multiprocessing import Process
from pathlib import Path

from ismain import is_main

from pytest_fly import main


class Visualize(Process):
    def run(self):
        main()


def generate_tests():
    # generate tests

    # Files must match pytest's default `test_*.py` discovery pattern; the prior
    # `fly_case_*` prefix collected zero tests and the suite never ran.
    test_file_prefix = "test_fly_case"
    test_dir = Path("fly_demo")
    test_dir.mkdir(exist_ok=True, parents=True)
    print(f'writing demo tests to "{test_dir.resolve()}"')
    # delete any existing tests
    for test_file in test_dir.glob(f"{test_file_prefix}*.py"):
        test_file.unlink()
    # Two test numbers fail intentionally so the GUI's Failed Tests panel is non-empty in
    # screenshots and so the per-tab visuals (Table state column, Coverage line) show variety.
    failing_test_numbers = {2, 7}
    groups = 3
    subgroups = 4
    for test_group in range(groups):
        test_case_file = Path(test_dir, f"{test_file_prefix}_{chr(test_group + ord('a'))}.py")
        with test_case_file.open("w") as f:
            f.write("import time\n")
            f.write("\n")
            for test_case in range(subgroups):
                test_number = test_group * subgroups + test_case
                # 1..4-second sleeps keep total wall time around ~10s with three parallel
                # modules — enough to show meaningful parallelism in the GUI without dragging
                # the demo (or the capture script's GIF) out unnecessarily.
                sleep_seconds = (test_number % subgroups) + 1
                if test_number in failing_test_numbers:
                    test_code = textwrap.dedent(
                        f"""
                        def test_case_{test_number}():
                            time.sleep({sleep_seconds})
                            assert False, "intentional demo failure"

                        """
                    )
                else:
                    test_code = textwrap.dedent(
                        f"""
                        def test_case_{test_number}():
                            time.sleep({sleep_seconds})

                        """
                    )
                f.write(test_code)


def demo():

    generate_tests()

    # start realtime watcher GUI; user clicks Run inside the GUI to launch the suite.
    visualize = Visualize()
    visualize.start()


if is_main():
    demo()
