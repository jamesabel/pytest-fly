from pathlib import Path
from enum import IntEnum

from attr import attrib, attrs
from pref import Pref, PrefOrderedSet
from appdirs import user_data_dir

from ..__version__ import application_name, author
from pytest_fly.common.platform_info import get_performance_core_count

preferences_file_name = f"{application_name}_preferences.db"

scheduler_time_quantum_default = 1.0
refresh_rate_default = 3.0
utilization_high_threshold_default = 0.8
utilization_low_threshold_default = 0.5


class Resume(IntEnum):
    RESTART = 0  # rerun all tests
    RESUME = 1  # resume test run, and run tests that either failed or were not run
    AUTO = 2  # resume if program under test has not changed, otherwise restart


class ParallelismControl(IntEnum):
    SERIAL = 0  # run tests serially (processes=1)
    PARALLEL = 1  # run "processes" number of tests in parallel
    DYNAMIC = 2  # automatically dynamically determine max number of processes to run in parallel, while trying to avoid high utilization thresholds (see utilization_high_threshold)


@attrs
class FlyPreferences(Pref):
    window_x: int = attrib(default=-1)
    window_y: int = attrib(default=-1)
    window_width: int = attrib(default=-1)
    window_height: int = attrib(default=-1)

    verbose: bool = attrib(default=False)
    scheduler_time_quantum: float = attrib(default=scheduler_time_quantum_default)  # scheduler time quantum in seconds
    refresh_rate: float = attrib(default=refresh_rate_default)  # display minimum refresh rate in seconds

    parallelism: int = attrib(default=ParallelismControl.SERIAL)  # 0=serial, 1=parallel, 2=dynamic
    processes: int = attrib(default=get_performance_core_count())  # fixed number of processes to use for "PARALLEL" mode

    utilization_high_threshold: float = attrib(default=utilization_high_threshold_default)  # above this threshold is considered high utilization
    utilization_low_threshold: float = attrib(default=utilization_low_threshold_default)  # below this threshold is considered low utilization

    resume: int = attrib(default=Resume.AUTO)  # 0=restart all tests, 1=resume, 2=auto resume if possible (i.e. program version under test has not changed)
    csv_dump_path: str = attrib(default=str(Path(user_data_dir(application_name, author), f"{application_name}.csv")))


def get_pref() -> FlyPreferences:
    return FlyPreferences(application_name, author, file_name=preferences_file_name)


class PrefSplits(PrefOrderedSet):
    def __init__(self):
        super().__init__(application_name, author, "split", preferences_file_name)


def get_splits() -> PrefOrderedSet:
    return PrefSplits()
