"""Tests for pytest_fly.faults — faulthandler arming and the post-crash sweep."""

import faulthandler
import logging
import multiprocessing
import os
from pathlib import Path

import pytest

from pytest_fly import faults
from pytest_fly.const import PYTEST_FLY_FAULTHANDLER_STRING
from pytest_fly.paths import get_log_dir, init_workspace


@pytest.fixture
def fault_workspace(tmp_path, monkeypatch):
    """Isolated workspace plus a clean environment, restoring the session workspace afterwards."""
    from pytest_fly import paths

    previous = paths.get_workspace_dir()
    monkeypatch.delenv(PYTEST_FLY_FAULTHANDLER_STRING, raising=False)
    init_workspace(tmp_path)
    was_enabled = faulthandler.is_enabled()
    yield tmp_path
    faulthandler.disable()
    if was_enabled:
        faulthandler.enable()
    init_workspace(previous)


def test_enabled_by_env_defaults_true(fault_workspace, monkeypatch):
    assert faults.faulthandler_enabled_by_env() is True
    for falsy in ("0", "false", "no"):
        monkeypatch.setenv(PYTEST_FLY_FAULTHANDLER_STRING, falsy)
        assert faults.faulthandler_enabled_by_env() is False
    monkeypatch.setenv(PYTEST_FLY_FAULTHANDLER_STRING, "1")
    assert faults.faulthandler_enabled_by_env() is True


def test_disabled_creates_nothing_and_leaves_env_alone(fault_workspace):
    assert faults.enable_faulthandler(requested=False) is None
    assert not faults.faulthandler_dump_path().exists()
    assert PYTEST_FLY_FAULTHANDLER_STRING not in os.environ


def test_enabled_creates_dump_file(fault_workspace):
    path = faults.enable_faulthandler(requested=True)
    assert path == faults.faulthandler_dump_path()
    assert path.exists()
    assert faulthandler.is_enabled()


def test_export_to_children_stamps_environment(fault_workspace):
    faults.enable_faulthandler(export_to_children=True, requested=False)
    assert os.environ[PYTEST_FLY_FAULTHANDLER_STRING] == "0"
    faults.enable_faulthandler(export_to_children=True, requested=True)
    assert os.environ[PYTEST_FLY_FAULTHANDLER_STRING] == "1"


def test_report_previous_crashes(fault_workspace, caplog):
    log_dir = get_log_dir()
    empty = log_dir / "faulthandler-111.log"
    empty.write_bytes(b"")
    crashed = log_dir / "faulthandler-222.log"
    crashed.write_text('Fatal Python error: Segmentation fault\n\nThread 0x0001 (most recent call first):\n  File "x.py", line 1 in f\n')
    own = faults.faulthandler_dump_path()
    own.write_text("must be skipped: this is the live file")

    with caplog.at_level(logging.WARNING):
        archived = faults.report_previous_crashes()

    assert not empty.exists()  # clean exit: deleted
    assert not crashed.exists()  # renamed, never destroyed
    assert archived == [log_dir / "faulthandler-crash-222-1.log"]
    assert archived[0].read_text().startswith("Fatal Python error")
    assert own.exists()  # own live file untouched
    assert any("previous session crashed" in r.message and "Segmentation fault" in r.message for r in caplog.records)
    assert all(getattr(r, "fly_event", False) for r in caplog.records if "previous session crashed" in r.message)

    # Idempotent: nothing new to report, the archive is not re-reported or renamed again.
    assert faults.report_previous_crashes() == []
    assert archived[0].exists()


def test_archive_numbering_never_overwrites(fault_workspace):
    log_dir = get_log_dir()
    (log_dir / "faulthandler-crash-333-1.log").write_text("older crash, same pid reused")
    (log_dir / "faulthandler-333.log").write_text("newer crash")
    archived = faults.report_previous_crashes()
    assert archived == [log_dir / "faulthandler-crash-333-2.log"]
    assert (log_dir / "faulthandler-crash-333-1.log").read_text() == "older crash, same pid reused"


def _crash_child() -> None:
    """Spawn-child body: arm the handler from the inherited environment, then die from a real fault."""
    from pytest_fly.faults import enable_faulthandler

    enable_faulthandler()
    faulthandler._sigsegv()  # noqa: SLF001 — the documented test hook for a genuine segfault


def test_child_crash_leaves_named_dump(fault_workspace, monkeypatch):
    """End to end: a child that segfaults for real leaves a non-empty dump naming its frame."""
    monkeypatch.setenv(PYTEST_FLY_FAULTHANDLER_STRING, "1")
    child = multiprocessing.get_context("spawn").Process(target=_crash_child)
    child.start()
    child.join(120)
    assert not child.is_alive()
    assert child.exitcode != 0
    dump = faults.faulthandler_dump_path(child.pid)
    assert dump.exists()
    text = dump.read_text(errors="replace")
    assert "_crash_child" in text
    assert Path(dump).stat().st_size > 0
    # And the next launch's sweep surfaces it.
    archived = faults.report_previous_crashes()
    assert len(archived) == 1 and "_crash_child" in archived[0].read_text(errors="replace")
