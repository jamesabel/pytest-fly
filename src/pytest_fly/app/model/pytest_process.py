from dataclasses import dataclass

from pytest import ExitCode

from ...common import PytestProcessState, PytestStatus


def exit_code_to_string(exit_code: ExitCode | None) -> str:
    if exit_code is None:
        exit_code_string = str(exit_code)
    else:
        exit_code_string = exit_code.name
    return exit_code_string


@dataclass(frozen=True)
class PytestKey:
    """
    Represents a unique key for a test and state.
    """

    name: str
    state: PytestProcessState


def key_from_pytest_status(status: PytestStatus) -> PytestKey:
    return PytestKey(name=status.name, state=status.state)
