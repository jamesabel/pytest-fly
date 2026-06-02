"""Part B — stall watchdog signal and opt-in escalation.

Drives the watchdog's tick() directly with an injected fake clock, progress source, and CPU
sampler so the signal is deterministic and host-independent.
"""

from pathlib import Path

from pytest_fly.pytest_runner.pytest_runner import _StallConfig, _StallWatchdog


def _progress_fixed():
    """Fixed fingerprint (no transitions), one stuck running test with pid 4321."""
    return ((1, 1, 100.0), ["tests/test_a.py"], [4321], 2)


def _idle(pid):
    return 0.0


def _busy(pid):
    return 50.0  # well above the default epsilon


def _make_watchdog(config, progress_source, cpu_sampler, clock, is_running=None, escalate=None):
    return _StallWatchdog(
        "run-guid",
        Path("."),
        controller_pid=None,  # skip the descendant-count walk in tests
        config=config,
        is_running_fn=is_running or (lambda: True),
        escalate_fn=escalate or (lambda: None),
        sample_interval=1.0,
        clock=clock,
        cpu_sampler=cpu_sampler,
        progress_source=progress_source,
    )


def test_stall_flags_after_no_progress_and_idle_cpu():
    t = {"now": 0.0}
    wd = _make_watchdog(_StallConfig(enabled=True, warn_seconds=600.0), _progress_fixed, _idle, lambda: t["now"])

    wd.tick()  # primes fingerprint at t=0, resets timer
    assert wd.is_stalled() is False

    t["now"] = 601.0
    wd.tick()
    info = wd.get_stall_info()
    assert info.stalled is True
    assert info.stuck_tests == ["tests/test_a.py"]
    assert info.idle_pids == [4321]


def test_active_cpu_never_flags_regardless_of_elapsed():
    t = {"now": 0.0}
    wd = _make_watchdog(_StallConfig(enabled=True, warn_seconds=600.0, cpu_active_epsilon=1.0), _progress_fixed, _busy, lambda: t["now"])

    wd.tick()
    for elapsed in (601.0, 5000.0, 100000.0):
        t["now"] = elapsed
        wd.tick()
        assert wd.is_stalled() is False, f"a CPU-active test must never flag (elapsed={elapsed})"


def test_db_transition_resets_timer():
    t = {"now": 0.0}
    state = {"fp": (0, 1, 100.0)}

    def progress():
        return (state["fp"], ["tests/test_a.py"], [4321], 2)

    wd = _make_watchdog(_StallConfig(enabled=True, warn_seconds=600.0), progress, _idle, lambda: t["now"])

    wd.tick()  # prime
    t["now"] = 590.0
    state["fp"] = (1, 1, 200.0)  # a test finished -> transition
    wd.tick()
    assert wd.is_stalled() is False

    t["now"] = 700.0  # only 110s since the transition reset the timer
    wd.tick()
    assert wd.is_stalled() is False


def test_not_running_is_never_stalled():
    t = {"now": 0.0}
    wd = _make_watchdog(_StallConfig(enabled=True, warn_seconds=600.0), _progress_fixed, _idle, lambda: t["now"], is_running=lambda: False)
    wd.tick()
    t["now"] = 10000.0
    wd.tick()
    assert wd.is_stalled() is False


def test_no_auto_escalation_when_disabled():
    t = {"now": 0.0}
    calls = {"n": 0}
    wd = _make_watchdog(
        _StallConfig(enabled=True, warn_seconds=600.0, auto_force_stop=False, kill_seconds=1800.0),
        _progress_fixed,
        _idle,
        lambda: t["now"],
        escalate=lambda: calls.__setitem__("n", calls["n"] + 1),
    )
    wd.tick()
    t["now"] = 100000.0
    wd.tick()
    assert calls["n"] == 0


def test_auto_escalation_invokes_once_after_kill_seconds():
    t = {"now": 0.0}
    calls = {"n": 0}
    wd = _make_watchdog(
        _StallConfig(enabled=True, warn_seconds=600.0, auto_force_stop=True, kill_seconds=1800.0),
        _progress_fixed,
        _idle,
        lambda: t["now"],
        escalate=lambda: calls.__setitem__("n", calls["n"] + 1),
    )
    wd.tick()  # prime

    t["now"] = 700.0  # past warn, before kill -> stalled but no escalation
    wd.tick()
    assert wd.is_stalled() is True
    assert calls["n"] == 0

    t["now"] = 1900.0  # past kill -> escalate once
    wd.tick()
    assert calls["n"] == 1

    t["now"] = 5000.0  # still stalled, but must not escalate again
    wd.tick()
    assert calls["n"] == 1
