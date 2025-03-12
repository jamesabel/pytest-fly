import sys
from io import StringIO
from pathlib import Path

import pytest
from typeguard import typechecked

from .logging import get_logger

log = get_logger()


@typechecked
def get_tests(test_dir: Path = Path(".").resolve()) -> list[str]:
    """
    Collects all pytest tests within the given directory (recursively)
    and returns their node IDs as a list of strings.

    :param test_dir: Directory in which to discover pytest tests.
    :return: A list of discovered test node IDs.
    """
    original_stdout = sys.stdout
    buffer = StringIO()

    try:
        # Temporarily redirect stdout so we can parse pytest’s collection output.
        sys.stdout = buffer

        # Instruct pytest to only collect tests (no execution) quietly.
        # The -q (quiet) flag makes the output more predictable.
        pytest.main(["--collect-only", "-q", str(test_dir)])
    finally:
        # Restore the original stdout
        sys.stdout = original_stdout

    # The buffer now contains lines with test node IDs plus possibly other text
    lines = buffer.getvalue().strip().split("\n")

    # Filter out lines that don't look like test node IDs.
    # A simplistic approach is to keep lines containing '::' (the typical pytest node-id pattern).
    delimiter = "::"

    node_ids_set = set(([str(line.split(delimiter)[0]) for line in lines if delimiter in line]))
    node_ids = sorted(node_ids_set)

    log.info(f'Discovered {len(node_ids)} pytest tests in "{test_dir}"')

    return node_ids
