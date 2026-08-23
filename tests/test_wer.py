"""Tests for pytest_fly.platform.wer — read-only and command-building paths.

The elevated write is deliberately untested: it needs admin rights and mutates machine state.
"""

import logging
import time
from pathlib import Path

from pytest_fly.platform import wer
from pytest_fly.preferences import get_pref


def test_read_unconfigured_image_is_safe():
    """A subkey that cannot exist reads as unconfigured, with no exception on any platform."""
    config = wer.read_wer_local_dumps("pytest-fly-no-such-image-xyz.exe")
    assert config.configured is False
    assert config.dump_folder is None and config.dump_count is None and config.dump_type is None
    assert "Not configured" in config.describe()


def test_read_on_non_windows_skips_winreg(monkeypatch):
    monkeypatch.setattr(wer, "is_windows", lambda: False)
    assert wer.read_wer_local_dumps().configured is False
    assert wer._run_elevated_powershell("anything") is False


def test_configure_command_is_stable_and_quotes_spaces():
    command = wer.wer_configure_command("python.exe", Path(r"C:\my work space\dumps"), 3, 1)
    assert command == wer.wer_configure_command("python.exe", Path(r"C:\my work space\dumps"), 3, 1)
    assert r"LocalDumps\python.exe" in command
    assert "'C:\\my work space\\dumps'" in command
    assert "-Name DumpCount -PropertyType DWord -Value 3" in command
    assert "-Name DumpType -PropertyType DWord -Value 1" in command
    assert "-Name DumpFolder -PropertyType ExpandString" in command


def test_remove_command_targets_image_key():
    assert wer.wer_remove_command("python.exe").startswith("Remove-Item -Path 'HKLM:\\")
    assert "LocalDumps\\python.exe'" in wer.wer_remove_command("python.exe")


def test_describe_configured():
    config = wer.WerLocalDumpsConfig("python.exe", True, r"C:\dumps", 3, wer.DUMP_TYPE_MINIDUMP)
    assert config.describe() == r"python.exe → C:\dumps, type=minidump, count=3"


def test_report_previous_crash_dumps_reports_new_files_once(tmp_path, caplog):
    pref = get_pref()
    pref.wer_dump_folder = str(tmp_path)
    pref.last_crash_dump_sweep = 0.0
    dump = tmp_path / "python.exe.1234.dmp"
    dump.write_bytes(b"MDMP" + b"\0" * 100)
    (tmp_path / "unrelated.txt").write_text("ignored")

    with caplog.at_level(logging.WARNING):
        reported = wer.report_previous_crash_dumps()
    assert reported == [dump]
    assert any("crash dump from a previous session" in r.message and "1234" in r.message for r in caplog.records)
    assert pref.last_crash_dump_sweep >= dump.stat().st_mtime

    # Second sweep: nothing new.
    assert wer.report_previous_crash_dumps() == []

    # A newer dump is picked up.
    time.sleep(0.05)
    newer = tmp_path / "python.exe.5678.dmp"
    newer.write_bytes(b"MDMP")
    future = pref.last_crash_dump_sweep + 1.0
    import os

    os.utime(newer, (future, future))
    assert wer.report_previous_crash_dumps() == [newer]

    pref.wer_dump_folder = ""
    pref.last_crash_dump_sweep = 0.0
