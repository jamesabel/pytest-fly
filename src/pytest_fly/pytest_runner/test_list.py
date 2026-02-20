import sys
from io import StringIO
from pathlib import Path
from multiprocessing import Process, Queue
from queue import Empty

import pytest
from typeguard import typechecked

from ..logger import get_logger
from ..interfaces import ScheduledTest

log = get_logger()


class GetTests(Process):

    def __init__(self, test_dir: Path = Path("").resolve()):
        """
        Collects all pytest tests within the given directory (recursively) in a separate process and returns their node IDs as a list of strings.

        :param test_dir: Directory in which to discover pytest tests.
        """
        self.test_dir = test_dir
        self.scheduled_tests: list[ScheduledTest] = []
        self._scheduled_tests_queue = Queue()
        super().__init__()

    @typechecked
    def run(self):
        log.info(f"{self.test_dir=}")

        # value is True if the test is marked with 'singleton', False otherwise
        pytest_tests = {}  # type: dict[str, bool]

        # singleton last
        for collect_singleton in (False, True):

            # Temporarily redirect stdout so we can parse pytest’s collection output.
            original_stdout = sys.stdout
            buffer = StringIO()
            sys.stdout = buffer

            try:
                # Instruct pytest to only collect tests (no execution) quietly.
                # -q (quiet) flag makes the output more predictable.
                collect_parameters = ["--collect-only", "-q"]
                # "-m singleton" is used to filter tests by the ‘singleton’ marker. "-m not singleton" is used to filter out tests with the ‘singleton’ marker.
                if collect_singleton:
                    collect_parameters.extend(["-m", "singleton"])
                collect_parameters.append(str(self.test_dir))

                pytest.main(collect_parameters)

                # The buffer now contains lines with test node IDs plus possibly other text
                buffer_value = buffer.getvalue()
                lines = buffer_value.strip().split("\n")

                # Filter out lines that don’t look like test node IDs.
                # A simplistic approach is to keep lines containing ‘::’ (the typical pytest node-id pattern).
                delimiter = "::"

                for line in lines:
                    if delimiter in line:
                        # Extract the node ID from the line.
                        # The node ID is typically the first part of the line before the delimiter.
                        node_id = line.split(delimiter)[0]
                        pytest_tests[node_id] = collect_singleton
            finally:
                # Restore the original stdout
                sys.stdout = original_stdout

        # todo: add test execution time and coverage to enable proper sorting
        for node_id, singleton in pytest_tests.items():
            self._scheduled_tests_queue.put(ScheduledTest(node_id, singleton, None, None))

        log.info(f'Discovered {len(pytest_tests)} pytest tests in "{self.test_dir}"')

    def get_tests(self) -> list[ScheduledTest]:
        """
        Returns the list of scheduled tests after the process has run.
        """
        try:
            while test := self._scheduled_tests_queue.get(False):
                self.scheduled_tests.append(test)
        except Empty:
            pass

        self.scheduled_tests.sort()

        return self.scheduled_tests
