"""Tests for pytest_runner.system_monitor."""

import time
from queue import Empty

from pytest_fly.pytest_runner.system_monitor import SystemMonitor, SystemMonitorSample


def test_system_monitor_emits_sample():
    monitor = SystemMonitor(update_rate=0.2)
    monitor.start()
    try:
        time.sleep(1.0)
    finally:
        monitor.request_stop()
        monitor.join(10.0)

    assert not monitor.is_alive()

    samples: list[SystemMonitorSample] = []
    while True:
        try:
            samples.append(monitor.system_monitor_queue.get_nowait())
        except Empty:
            break

    assert samples, "expected at least one sample"
    sample = samples[0]
    assert 0.0 <= sample.cpu_percent <= 100.0 * 64
    assert 0.0 <= sample.memory_percent <= 100.0
    assert sample.memory_total_gb > 0.0
    assert sample.memory_used_gb >= 0.0
    assert sample.disk_read_mbps >= 0.0
    assert sample.disk_write_mbps >= 0.0
    assert sample.net_sent_mbps >= 0.0
    assert sample.net_recv_mbps >= 0.0
