"""
Live pytest output files — single source of truth for the per-test log path and
read/clear helpers.

Each running test writes its stdout/stderr to ``data_dir/live_output/<safe>.log``
(line-buffered) in :class:`PytestProcess`.  The GUI polls the tail of that file
to render live output for RUNNING tests before the final completed output lands
in the database.
"""

from pathlib import Path

from ..file_util import sanitize_test_name

_LIVE_OUTPUT_SUBDIR = "live_output"
_TRUNCATION_MARKER = "...[truncated]...\n"

# Cache decoded live-output text keyed by path, invalidated by (size, mtime_ns).
# GUI ticks call read_live_output once per running test per tick just to keep
# table tooltips current; this avoids the re-read + UTF-8 decode when the file
# on disk has not changed.
_read_cache: dict[Path, tuple[int, int, str]] = {}


def live_output_dir(data_dir: Path) -> Path:
    """Return the directory that holds per-test live-output log files."""
    return Path(data_dir, _LIVE_OUTPUT_SUBDIR)


def live_output_path(data_dir: Path, test_name: str) -> Path:
    """Return the live-output log file path for a given test node id."""
    return Path(live_output_dir(data_dir), f"{sanitize_test_name(test_name)}.log")


def read_live_output(data_dir: Path, test_name: str, max_bytes: int = 65536) -> str | None:
    """Return the tail of the live-output log for a test, or ``None`` if missing.

    Reads at most ``max_bytes`` from the end of the file.  If the file is
    larger, the first (likely partial) line is dropped and a short truncation
    marker is prepended so the user can see output is elided.

    Decodes with ``errors="replace"`` so non-UTF-8 bytes don't crash the GUI.
    """
    path = live_output_path(data_dir, test_name)
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        _read_cache.pop(path, None)
        return None
    file_size = stat_result.st_size
    mtime_ns = stat_result.st_mtime_ns
    cached = _read_cache.get(path)
    if cached is not None and cached[0] == file_size and cached[1] == mtime_ns:
        return cached[2]
    with open(path, "rb") as fh:
        truncated = file_size > max_bytes
        if truncated:
            fh.seek(-max_bytes, 2)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    if truncated:
        newline_index = text.find("\n")
        if newline_index != -1:
            text = text[newline_index + 1 :]
        text = _TRUNCATION_MARKER + text
    _read_cache[path] = (file_size, mtime_ns, text)
    return text


def clear_live_output(data_dir: Path) -> None:
    """Remove the entire live-output directory; safe if it does not exist."""
    directory = live_output_dir(data_dir)
    _read_cache.clear()
    if not directory.exists():
        return
    for entry in directory.iterdir():
        try:
            entry.unlink()
        except OSError:
            pass
    try:
        directory.rmdir()
    except OSError:
        pass
