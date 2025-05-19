from pathlib import Path
from enum import IntEnum

from attr import attrib, attrs
from pref import Pref, PrefOrderedSet
from platformdirs import user_data_dir
from tobool import to_bool_strict

from ...__version__ import application_name, author
from ..model import RunMode, get_performance_core_count

preferences_file_name = f"{application_name}_preferences.db"

scheduler_time_quantum_default = 1.0
refresh_rate_default = 3.0
utilization_high_threshold_default = 0.8
utilization_low_threshold_default = 0.5
run_with_coverage_default = True


class ParallelismControl(IntEnum):
    SERIAL = 0  # run tests serially (processes=1)
    PARALLEL = 1  # run "processes" number of tests in parallel
    DYNAMIC = 2  # automatically dynamically determine max number of processes to run in parallel, while trying to avoid high utilization thresholds (see utilization_high_threshold)


def get_default_data_directory() -> Path:
    """
    Get the default data directory for the application. May be used to reset preference back to default.
    """
    default_user_data_directory = Path(user_data_dir(application_name, author))
    return default_user_data_directory


@attrs
class FlyPreferences(Pref):

    window_x: int = attrib(default=-1)
    window_y: int = attrib(default=-1)
    window_width: int = attrib(default=-1)
    window_height: int = attrib(default=-1)

    verbose: bool = attrib(default=False)
    scheduler_time_quantum: float = attrib(default=scheduler_time_quantum_default)  # scheduler time quantum in seconds
    refresh_rate: float = attrib(default=refresh_rate_default)  # display minimum refresh rate in seconds

    parallelism: ParallelismControl = attrib(default=ParallelismControl.SERIAL)  # 0=serial, 1=parallel, 2=dynamic
    processes: int = attrib(default=get_performance_core_count())  # fixed number of processes to use for "PARALLEL" mode

    utilization_high_threshold: float = attrib(default=utilization_high_threshold_default)  # above this threshold is considered high utilization
    utilization_low_threshold: float = attrib(default=utilization_low_threshold_default)  # below this threshold is considered low utilization

    run_mode: RunMode = attrib(default=RunMode.CHECK)  # 0=restart all tests, 1=resume, 2=resume if possible (i.e., the program version under test has not changed)

    run_with_coverage: bool = attrib(default=run_with_coverage_default)  # run with coverage

    data_directory = attrib(default=str(get_default_data_directory()))

    def get_run_with_coverage(self) -> bool:
        return to_bool_strict(self.run_with_coverage)


def get_pref() -> FlyPreferences:
    return FlyPreferences(application_name, author, file_name=preferences_file_name)


class PrefSplits(PrefOrderedSet):
    def __init__(self):
        super().__init__(application_name, author, "split", preferences_file_name)


def get_splits() -> PrefOrderedSet:
    return PrefSplits()
