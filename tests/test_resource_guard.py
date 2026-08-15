"""Resource guard — low-resource automatic soft stop.

Drives the guard's tick() directly with injected disk/commit samplers so the signal is
deterministic and host-independent (same approach as the stall-watchdog tests).
"""

from pathlib import Path

from pytest_fly.pytest_runner.resource_guard import ResourceGuard, ResourceGuardConfig, consecutive_breaches_to_trigger


def _make_guard(config, disk_free_sampler, commit_sampler, soft_stop=None, is_running=None):
    return ResourceGuard(
        "run-guid",
        Path("."),
        config,
        is_running_fn=is_running or (lambda: True),
        soft_stop_fn=soft_stop or (lambda: None),
        sample_interval=1.0,
        disk_free_sampler=disk_free_sampler,
        commit_sampler=commit_sampler,
    )


def _counter():
    calls = {"n": 0}

    def soft_stop():
        calls["n"] += 1

    return calls, soft_stop


def test_healthy_resources_never_trigger():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: 100.0, lambda: 0.50, soft_stop)
    for _tick_index in range(10):
        guard.tick()
    assert calls["n"] == 0
    info = guard.get_info()
    assert info.triggered is False
    assert info.reason == ""
    assert info.free_disk_gb == 100.0
    assert info.commit_fraction == 0.50


def test_low_disk_triggers_after_consecutive_breaches():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: 2.5, lambda: 0.50, soft_stop)

    for _tick_index in range(consecutive_breaches_to_trigger - 1):
        guard.tick()
    assert calls["n"] == 0, "a single (non-sustained) breach must not trigger"

    guard.tick()
    assert calls["n"] == 1
    info = guard.get_info()
    assert info.triggered is True
    assert "disk" in info.reason


def test_high_commit_triggers_after_consecutive_breaches():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: 100.0, lambda: 0.99, soft_stop)
    for _tick_index in range(consecutive_breaches_to_trigger):
        guard.tick()
    assert calls["n"] == 1
    assert "commit" in guard.get_info().reason


def test_transient_breach_resets_consecutive_counter():
    calls, soft_stop = _counter()
    readings = iter([2.5, 100.0, 2.5, 100.0, 2.5, 100.0])
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: next(readings), lambda: 0.50, soft_stop)
    for _tick_index in range(6):
        guard.tick()
    assert calls["n"] == 0, "alternating breach/healthy samples must never accumulate to a trigger"


def test_triggers_at_most_once_per_run():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: 2.5, lambda: 0.99, soft_stop)
    for _tick_index in range(10):
        guard.tick()
    assert calls["n"] == 1, "the guard is a one-shot latch — a canceled auto-stop must not be re-fired"
    assert guard.get_info().triggered is True


def test_unavailable_signals_fail_open():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: None, lambda: None, soft_stop)
    for _tick_index in range(10):
        guard.tick()
    assert calls["n"] == 0
    info = guard.get_info()
    assert info.free_disk_gb is None
    assert info.commit_fraction is None


def test_zero_min_free_disk_disables_disk_check():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=0.0, commit_threshold=0.95), lambda: 0.001, lambda: 0.50, soft_stop)
    for _tick_index in range(10):
        guard.tick()
    assert calls["n"] == 0


def test_both_breaches_reported_in_reason():
    calls, soft_stop = _counter()
    guard = _make_guard(ResourceGuardConfig(enabled=True, min_free_disk_gb=10.0, commit_threshold=0.95), lambda: 2.5, lambda: 0.99, soft_stop)
    for _tick_index in range(consecutive_breaches_to_trigger):
        guard.tick()
    reason = guard.get_info().reason
    assert "disk" in reason
    assert "commit" in reason


def test_default_samplers_read_real_host():
    """The default samplers must return sane values (or None) on the host without raising."""
    guard = ResourceGuard(
        "run-guid",
        Path("."),
        ResourceGuardConfig(enabled=True),
        is_running_fn=lambda: True,
        soft_stop_fn=lambda: None,
        sample_interval=1.0,
    )
    free_gb = guard._default_disk_free_sampler()
    assert free_gb is None or free_gb > 0.0
    commit_fraction = guard._default_commit_sampler()
    assert commit_fraction is None or 0.0 < commit_fraction <= 1.5  # commit can briefly exceed a shrinking limit
