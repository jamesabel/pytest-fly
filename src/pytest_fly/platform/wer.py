"""Windows Error Reporting (WER) *LocalDumps* support.

When a process dies from a native fault (e.g. an access violation inside ``python314.dll``),
WER produces a minidump — and then discards it unless ``LocalDumps`` is configured.  That
configuration lives under ``HKLM`` and so requires elevation to write; pytest-fly can *read* it
and *offer* to apply it (via a UAC prompt), but never applies it silently.

The setting is keyed on the bare image name (``python.exe``), so it is machine-wide and covers
every Python process on the box, not just pytest-fly.  The UI says so.

Everything here imports cleanly on non-Windows: ``winreg`` and the ``ctypes`` shell call are
confined to Windows-only branches.
"""

import ctypes
import time
from dataclasses import dataclass
from pathlib import Path

from ..logger import EVENT_EXTRA, get_logger
from ..paths import get_fly_data_dir
from .os import is_windows

log = get_logger()

LOCAL_DUMPS_KEY = r"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps"
DEFAULT_IMAGE_NAME = "python.exe"
DUMP_TYPE_MINIDUMP = 1
DUMP_TYPE_FULL = 2
_crash_dump_subdir_name = "crashdumps"
_shell_execute_launched_threshold = 32  # ShellExecuteW returns > 32 on success


@dataclass(frozen=True)
class WerLocalDumpsConfig:
    """Current LocalDumps registry state for one image name."""

    image_name: str
    configured: bool
    dump_folder: str | None
    dump_count: int | None
    dump_type: int | None

    def describe(self) -> str:
        """One-line human-readable status for the Configuration tab."""
        if not self.configured:
            return f"Not configured — Windows discards crash dumps for {self.image_name}"
        type_name = {DUMP_TYPE_MINIDUMP: "minidump", DUMP_TYPE_FULL: "full"}.get(self.dump_type or 0, str(self.dump_type))
        folder = self.dump_folder or "%LOCALAPPDATA%\\CrashDumps (default)"
        count = self.dump_count if self.dump_count is not None else "10 (default)"
        return f"{self.image_name} → {folder}, type={type_name}, count={count}"


def default_wer_dump_folder() -> Path:
    """``<workspace>/.pytest-fly/crashdumps`` — crash artifacts sit with the logs and results DB."""
    return Path(get_fly_data_dir(), _crash_dump_subdir_name)


def read_wer_local_dumps(image_name: str = DEFAULT_IMAGE_NAME) -> WerLocalDumpsConfig:
    """Read the LocalDumps subkey for *image_name*.  Unprivileged; never raises.

    On non-Windows platforms returns ``configured=False`` without touching ``winreg``.
    """
    unconfigured = WerLocalDumpsConfig(image_name, False, None, None, None)
    if not is_windows():
        return unconfigured
    import winreg  # Windows-only module

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{LOCAL_DUMPS_KEY}\\{image_name}")
    except FileNotFoundError:
        return unconfigured
    except OSError as e:
        log.info(f"could not read WER LocalDumps for {image_name}: {e}")
        return unconfigured
    with key:
        return WerLocalDumpsConfig(
            image_name,
            True,
            _read_value(key, "DumpFolder"),
            _read_value(key, "DumpCount"),
            _read_value(key, "DumpType"),
        )


def _read_value(key, name: str):
    """Return a registry value, or ``None`` when it is absent (WER then uses its default)."""
    import winreg  # Windows-only module

    try:
        value, _unused_type = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    except OSError as e:
        log.info(f"could not read WER LocalDumps value {name}: {e}")
        return None
    return value


def wer_configure_command(image_name: str, dump_folder: Path, dump_count: int, dump_type: int) -> str:
    """Return the elevated PowerShell command that would apply this configuration.

    Shown in the UI and offered for copy-to-clipboard, so the user can inspect exactly what will
    be written to HKLM before agreeing to run it.  The folder is single-quoted (PowerShell
    literal string) because workspace paths commonly contain spaces.
    """
    key = f"HKLM:\\{LOCAL_DUMPS_KEY}\\{image_name}"
    folder = str(dump_folder).replace("'", "''")
    return (
        f"New-Item -Path '{key}' -Force | Out-Null; "
        f"New-ItemProperty -Path '{key}' -Name DumpFolder -PropertyType ExpandString -Value '{folder}' -Force | Out-Null; "
        f"New-ItemProperty -Path '{key}' -Name DumpCount -PropertyType DWord -Value {int(dump_count)} -Force | Out-Null; "
        f"New-ItemProperty -Path '{key}' -Name DumpType -PropertyType DWord -Value {int(dump_type)} -Force | Out-Null"
    )


def wer_remove_command(image_name: str) -> str:
    """Return the elevated PowerShell command that deletes the LocalDumps subkey for *image_name*."""
    key = f"HKLM:\\{LOCAL_DUMPS_KEY}\\{image_name}"
    return f"Remove-Item -Path '{key}' -Recurse -Force"


def _run_elevated_powershell(command: str) -> bool:
    """Launch *command* in an elevated PowerShell via ShellExecuteW "runas".

    Returns whether the elevated process was *launched* — UAC consent and the registry write
    happen out-of-process, so callers must re-read the registry to learn the actual result.
    Deliberately a thin wrapper: it cannot be unit-tested without admin rights and a machine-state
    mutation, so it is kept obviously correct instead.
    """
    if not is_windows():
        return False
    args = f'-NoProfile -NonInteractive -Command "{command}"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", args, None, 0)  # type: ignore[attr-defined]
    launched = int(result) > _shell_execute_launched_threshold
    if not launched:
        log.warning(f"elevated PowerShell launch failed (ShellExecuteW returned {result}; 5 = UAC declined)")
    return launched


def apply_wer_local_dumps_elevated(image_name: str, dump_folder: Path, dump_count: int, dump_type: int) -> bool:
    """Launch the configure command elevated (UAC prompt).  See :func:`_run_elevated_powershell`."""
    try:
        dump_folder.mkdir(parents=True, exist_ok=True)  # WER does not reliably create a missing tree
    except OSError as e:
        log.warning(f"could not create WER dump folder {dump_folder}: {e}")
    return _run_elevated_powershell(wer_configure_command(image_name, dump_folder, dump_count, dump_type))


def remove_wer_local_dumps_elevated(image_name: str) -> bool:
    """Launch an elevated delete of the LocalDumps subkey for *image_name*."""
    return _run_elevated_powershell(wer_remove_command(image_name))


def report_previous_crash_dumps() -> list[Path]:
    """Log any ``*.dmp`` files in the configured dump folder that are newer than the last sweep.

    A dump nobody knows exists is no better than no dump.  Each new file is logged once at WARNING
    (visible in the Log tab), then the sweep timestamp preference advances past it.

    :return: the newly reported dump paths.
    """
    from ..preferences import get_pref  # deferred: preferences imports this package

    pref = get_pref()
    folder = Path(pref.wer_dump_folder) if pref.wer_dump_folder else default_wer_dump_folder()
    reported: list[Path] = []
    newest = pref.last_crash_dump_sweep
    if folder.is_dir():
        try:
            candidates = sorted(folder.glob("*.dmp"))
        except OSError as e:
            log.info(f"could not scan crash dump folder {folder}: {e}")
            candidates = []
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime > pref.last_crash_dump_sweep:
                log.warning(f"crash dump from a previous session: {path} ({stat.st_size / 1e6:.1f} MB, {time.ctime(stat.st_mtime)})", extra=EVENT_EXTRA)
                reported.append(path)
                newest = max(newest, stat.st_mtime)
    if newest != pref.last_crash_dump_sweep:
        pref.last_crash_dump_sweep = newest
    return reported
