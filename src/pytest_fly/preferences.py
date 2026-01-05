from enum import IntEnum

from attr import attrib, attrs
from pref import Pref

from .__version__ import application_name, author
from .platform import get_performance_core_count
from .interfaces import RunMode

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


@attrs
class FlyPreferences(Pref):

    window_x: int = attrib(default=-1)
    window_y: int = attrib(default=-1)
    window_width: int = attrib(default=-1)
    window_height: int = attrib(default=-1)

    verbose: bool = attrib(default=False)
    refresh_rate: float = attrib(default=refresh_rate_default)  # display minimum refresh rate in seconds

    parallelism: ParallelismControl = attrib(default=ParallelismControl.SERIAL)  # 0=serial, 1=parallel, 2=dynamic
    processes: int = attrib(default=get_performance_core_count())  # fixed number of processes to use for "PARALLEL" mode

    utilization_high_threshold: float = attrib(default=utilization_high_threshold_default)  # above this threshold is considered high utilization
    utilization_low_threshold: float = attrib(default=utilization_low_threshold_default)  # below this threshold is considered low utilization

    run_mode: RunMode = attrib(default=RunMode.CHECK)  # 0=restart all tests, 1=resume, 2=resume if possible (i.e., the program version under test has not changed)


def get_pref() -> FlyPreferences:
    return FlyPreferences(application_name, author, file_name=preferences_file_name)
