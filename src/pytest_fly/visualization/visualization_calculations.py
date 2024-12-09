from typing import List, Tuple, Dict
from collections import defaultdict

from ..db import RunInfo


def merge_intervals(intervals: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Merge overlapping intervals."""
    if not intervals:
        return []

    # Sort intervals by the start time
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]

    for current_start, current_end in intervals[1:]:
        last_end = merged[-1][1]

        if current_start <= last_end:
            merged[-1] = (merged[-1][0], max(last_end, current_end))
        else:
            merged.append((current_start, current_end))

    return merged


def calculate_utilization(data: Dict[str, Dict[str, RunInfo]]) -> Tuple[Dict[str, float], float]:
    """
    Calculate utilization for each worker and overall utilization.
    :param data: Dictionary with test names as keys and dictionaries with phase names as keys and RunInfo objects as values.
    :return: Tuple with a dictionary with worker IDs as keys and utilization as values and overall utilization.
    """
    worker_intervals = defaultdict(list)
    all_times = []

    # Collect intervals for each worker and all timestamps
    for test in data.values():
        for phase in test.values():
            worker_intervals[phase.worker_id].append((phase.start, phase.stop))
            all_times.extend([phase.start, phase.stop])

    # Calculate total time span
    if len(all_times) > 0:
        total_time_span = max(all_times) - min(all_times)

        # Calculate utilization for each worker
        utilization = {}
        total_busy_time_all_workers = 0
        for worker_id, intervals in worker_intervals.items():
            merged = merge_intervals(intervals)
            total_busy_time = sum(end - start for start, end in merged)
            total_busy_time_all_workers += total_busy_time  # Sum busy times for overall utilization
            if total_time_span > 0:
                utilization[worker_id] = total_busy_time / total_time_span

        # Calculate overall utilization
        num_processors = len(worker_intervals)
        if total_time_span > 0 and num_processors > 0:
            overall_utilization = total_busy_time_all_workers / (total_time_span * num_processors)
        else:
            overall_utilization = 0.0

    else:
        utilization = {}
        overall_utilization = 0

    return utilization, overall_utilization


class VisualizationCalculations:
    def __init__(self, run_info: dict):
        self.run_info = run_info

        self.sorted_data = dict(sorted(self.run_info.items(), key=lambda x: x[0]))
        self.worker_utilization, self.overall_utilization = calculate_utilization(self.sorted_data)
        if len(starts := [phase.start for test in self.sorted_data.values() for phase in test.values()]) > 0:
            self.earliest_start = min(starts)
        else:
            self.earliest_start = 0
        if len(stops := [phase.stop for test in self.sorted_data.values() for phase in test.values()]) > 0:
            self.latest_stop = max(stops)

        self.workers = set(info.worker_id for test in self.sorted_data.values() for info in test.values())
