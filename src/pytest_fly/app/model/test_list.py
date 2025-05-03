import sys
from io import StringIO
from pathlib import Path
from dataclasses import dataclass

import pytest
from typeguard import typechecked

from ..logger import get_logger

log = get_logger()


@typechecked
def get_tests(test_dir: Path = Path(".").resolve()) -> dict[str, bool]:
    """
    Collects all pytest tests within the given directory (recursively)
    and returns their node IDs as a list of strings.

    :param test_dir: Directory in which to discover pytest tests.
    :return: A list of discovered test node IDs.
    """

    log.info(f"{test_dir=}")

    # value is True if the test is marked with 'singleton', False otherwise
    pytest_tests = {}  # type: dict[str, bool]

    # singleton last
    for collect_singleton in (False, True):

        # Temporarily redirect stdout so we can parse pytest’s collection output.
        original_stdout = sys.stdout
        buffer = StringIO()
        sys.stdout = buffer

        # Instruct pytest to only collect tests (no execution) quietly.
        # -q (quiet) flag makes the output more predictable.
        collect_parameters = ["--collect-only", "-q"]
        # "-m singleton" is used to filter tests by the 'singleton' marker. "-m not singleton" is used to filter out tests with the 'singleton' marker.
        if collect_singleton:
            collect_parameters.extend(["-m", "singleton"])
        collect_parameters.append(str(test_dir))

        pytest.main(collect_parameters)

        # The buffer now contains lines with test node IDs plus possibly other text
        buffer_value = buffer.getvalue()
        lines = buffer_value.strip().split("\n")

        # Filter out lines that don't look like test node IDs.
        # A simplistic approach is to keep lines containing '::' (the typical pytest node-id pattern).
        delimiter = "::"

        pytest_set = set()
        for line in lines:
            if delimiter in line:
                # Extract the node ID from the line.
                # The node ID is typically the first part of the line before the delimiter.
                node_id = str(line.split(delimiter)[0])
                pytest_tests[node_id] = collect_singleton

        # Restore the original stdout
        sys.stdout = original_stdout

    log.info(f'Discovered {len(pytest_tests)} pytest tests in "{test_dir}"')

    return pytest_tests
