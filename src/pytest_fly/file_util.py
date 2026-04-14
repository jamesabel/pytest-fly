from pathlib import Path


def sanitize_test_name(name: str) -> str:
    """Convert a test node_id into a safe filesystem filename."""
    return name.replace("/", "_").replace("\\", "_")


def find_most_recent_file(directory: Path, pattern: str) -> Path | None:
    """
    Find the most recently modified file matching a glob pattern under a directory.

    Recursively searches *directory* for files matching *pattern* and returns
    the one with the newest modification time, or ``None`` if no match is found.

    :param directory: Root directory to search.
    :param pattern: Glob pattern passed to ``Path.rglob`` (e.g. ``"*.txt"``, ``"index.html"``).
    :return: Path to the most recently modified matching file, or ``None``.
    """
    best_path: Path | None = None
    best_mtime: float | None = None
    for file_path in directory.rglob(pattern):
        if file_path.is_file():
            mtime = file_path.stat().st_mtime
            if best_mtime is None or mtime > best_mtime:
                best_path = file_path
                best_mtime = mtime
    return best_path
