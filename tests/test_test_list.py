"""Tests for pytest_runner.test_list.GetTests."""

import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from pytest_fly.interfaces import ScheduledTest
from pytest_fly.pytest_runner.test_list import GetTests


def test_get_tests_discovers_node_ids():
    """GetTests must discover test node-ids from a directory of test files."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "test_alpha.py").write_text("def test_a():\n    assert True\n")
        (tmp_path / "test_beta.py").write_text("def test_b():\n    assert True\n")

        collector = GetTests(test_dir=tmp_path)
        collector.start()
        collector.join(60.0)

        assert not collector.is_alive()
        discovered = collector.get_tests()

        node_ids = [t.node_id for t in discovered]
        assert any("test_alpha.py" in nid for nid in node_ids), node_ids
        assert any("test_beta.py" in nid for nid in node_ids), node_ids

        for t in discovered:
            assert isinstance(t, ScheduledTest)
            assert t.singleton is False


def test_get_tests_marks_singleton():
    """Tests marked with @pytest.mark.singleton must be flagged as singletons."""
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "conftest.py").write_text("def pytest_configure(config):\n    config.addinivalue_line('markers', 'singleton: run this module alone')\n")
        (tmp_path / "test_solo.py").write_text("import pytest\n@pytest.mark.singleton\ndef test_solo():\n    assert True\n")
        (tmp_path / "test_shared.py").write_text("def test_shared():\n    assert True\n")

        collector = GetTests(test_dir=tmp_path)
        collector.start()
        collector.join(60.0)

        discovered = {t.node_id: t for t in collector.get_tests()}
        solo_entry = next((v for k, v in discovered.items() if "test_solo.py" in k), None)
        shared_entry = next((v for k, v in discovered.items() if "test_shared.py" in k), None)

        assert solo_entry is not None
        assert shared_entry is not None
        assert solo_entry.singleton is True
        assert shared_entry.singleton is False


def test_get_tests_empty_dir():
    """GetTests returns an empty list when the directory has no tests."""
    with TemporaryDirectory() as tmp:
        collector = GetTests(test_dir=Path(tmp))
        collector.start()
        collector.join(60.0)

        assert collector.get_tests() == []


class _ManyResults(GetTests):
    """Discovery stand-in that produces far more results than the queue pipe can buffer.

    ~5000 pickled ScheduledTests is well past the ~64 KB pipe buffer, so the child cannot
    exit until the parent drains — the deadlock GetTests.collect exists to prevent.
    """

    def run(self) -> None:
        for n in range(5000):
            self._scheduled_tests_queue.put(ScheduledTest(f"tests/test_{n:05d}.py", False, None, None))


class _NeverFinishes(GetTests):
    """Discovery stand-in that never completes (wedged collection)."""

    def run(self) -> None:
        time.sleep(600.0)


def test_collect_drains_large_result_sets_without_deadlock():
    """collect() must drain while the child runs; join-before-drain hung forever at ~500 modules."""
    collector = _ManyResults()
    collector.start()
    start = time.monotonic()
    tests = collector.collect(Event(), poll_seconds=0.1)
    elapsed = time.monotonic() - start
    assert tests is not None
    assert len(tests) == 5000
    assert tests == sorted(tests, key=lambda t: t.node_id)
    assert not collector.is_alive()
    assert elapsed < 30.0, f"collect took {elapsed:.1f}s"


def test_collect_aborts_wedged_discovery():
    """A set abort event must terminate discovery promptly and return None."""
    collector = _NeverFinishes()
    collector.start()
    abort = Event()
    abort.set()
    start = time.monotonic()
    result = collector.collect(abort, poll_seconds=0.1)
    elapsed = time.monotonic() - start
    assert result is None
    assert not collector.is_alive()
    assert elapsed < 15.0, f"abort took {elapsed:.1f}s"
