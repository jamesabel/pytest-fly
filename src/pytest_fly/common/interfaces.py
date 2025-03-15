from dataclasses import dataclass
# from multiprocessing import Manager, Lock
from enum import StrEnum, auto

from _pytest.config import ExitCode

class PytestProcessState(StrEnum):
    """
    Represents the state of a test process.
    """

    UNKNOWN = auto()  # unknown state
    QUEUED = auto()  # queued to be run by the PyTest runner scheduler
    RUNNING = auto()  # test is currently running
    FINISHED = auto()  # test has finished
    TERMINATED = auto()  # test was terminated




@dataclass
class PytestProcessInfo:
    """
    Information about a running test process, e.g. for the UI.
    """
    name: str
    state: PytestProcessState
    pid: int | None = None
    exit_code: ExitCode | None = None
    output: str | None = None
    start: float | None = None  # epoch when the test started (not when queued)
    end: float | None = None  # epoch when the test ended
    cpu_percent: float | None = None  # CPU utilization as a percentage (100.0 = 1 CPU)
    memory_percent: float | None = None  # memory utilization as a percentage (100.0 = 100% of RSS memory)



# class PytestProcesses:
#     """
#     Multiprocess manager for pytest processes dict. This is a separate class for typing.
#     """
#
#     def __init__(self):
#         self._manager = Manager()
#         self._processes = self._manager.dict()
#         self._lock = Lock()
#
#     def __getitem__(self, test: str) -> PytestProcessInfo:
#         return self._processes[test]
#
#     def __setitem__(self, test: str, value: PytestProcessInfo) -> None:
#         self._processes[test] = value
#
#     def __delitem__(self, test: str) -> None:
#         del self._processes[test]
#
#     def __iter__(self) -> iter:
#         return iter(self._processes)
#
#     def __len__(self) -> int:
#         return len(self._processes)
#
#     def __contains__(self, test: str) -> bool:
#         return test in self._processes
#
#     def items(self):
#         return self._processes.items()
#
#     def values(self):
#         return self._processes.values()

    # def update(self, test: str, value: PytestProcessInfo) -> None:
    #     """
    #     Update a value in the PytestProcessInfo that isn't a None. For example, this is handy for adding a test `exit_code` and `output`, but not changing the `start`.
    #     """
    #     with self._lock:
    #         class_instance = self._processes[test]
    #         for field in class_instance.__dataclass_fields__:
    #             if (v := getattr(value, field)) is not None:
    #                 setattr(class_instance, field, v)

def exit_code_to_string(exit_code: ExitCode | None) -> str:
    if exit_code is None:
        exit_code_string = str(exit_code)
    else:
        exit_code_string = exit_code.name
    return exit_code_string
