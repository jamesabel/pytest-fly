from enum import StrEnum, auto

TIMEOUT = 20.0


class PytestProcessState(StrEnum):
    """
    Represents the state of a test process.
    """

    UNKNOWN = auto()  # unknown state
    QUEUED = auto()  # queued to be run by the scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished
    TERMINATED = auto()  # test was terminated
