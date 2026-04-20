"""Tests for pytest_runner.process_monitor."""

import os
import time
from queue import Empty

from pytest_fly.guid import generate_uuid
from pytest_fly.pytest_runner.process_monitor import (
    ProcessMonitor,
    PytestProcessMonitorInfo,
    normalize_cpu_percent,
)


def test_normalize_cpu_percent_single_core_busy():
    assert normalize_cpu_percent(100.0, 1) == 100.0


def test_normalize_cpu_percent_scales_by_cores():
    assert normalize_cpu_percent(400.0, 4) == 100.0
    assert normalize_cpu_percent(50.0, 4) == 12.5


def test_normalize_cpu_percent_clamps_to_100():
    assert normalize_cpu_percent(9999.0, 2) == 100.0


def test_normalize_cpu_percent_zero_cores_guarded():
    assert normalize_cpu_percent(50.0, 0) == 50.0


def test_process_monitor_samples_own_process():
    run_guid = generate_uuid()
    monitor = ProcessMonitor(run_guid, name="self", pid=os.getpid(), update_rate=0.1)
    monitor.start()
    try:
        time.sleep(0.5)
    finally:
        monitor.request_stop()
        monitor.join(10.0)

    assert not monitor.is_alive()

    samples: list[PytestProcessMonitorInfo] = []
    while True:
        try:
            samples.append(monitor.process_monitor_queue.get_nowait())
        except Empty:
            break

    assert samples, "expected at least one sample"
    sample = samples[0]
    assert sample.run_guid == run_guid
    assert sample.pid == os.getpid()
    assert sample.cpu_percent is not None
    assert sample.memory_percent is not None
