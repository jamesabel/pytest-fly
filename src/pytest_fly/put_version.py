"""
Program-under-test (PUT) version detection.

Resolves the name, version, and git state of the project whose tests are being
run by pytest-fly.  Called once per run from :class:`ControlWindow.run` and the
result is stamped onto every :class:`PytestProcessInfo` record.

Detection cascade (first hit wins), rooted at a ``project_root`` that defaults
to the current working directory:

1. Explicit override (from preferences).
2. ``pyproject.toml`` walk-up: ``[project].name`` + ``[project].version``.
3. ``setup.cfg`` ``[metadata]`` ``name`` + ``version``.
4. ``importlib.metadata`` fallback — only when a package name was detected but
   the version was dynamic or missing (e.g., hatch-dynamic or setuptools_scm
   installed via ``pip install -e .``).

Git metadata (describe, SHA, branch, dirty flag) is captured independently when
a ``.git`` directory is present.  All helpers fail silently — detection never
blocks a run.
"""

from __future__ import annotations

import configparser
import subprocess
import tomllib
from importlib import metadata
from pathlib import Path

from .interfaces import PutVersionInfo
from .logger import get_logger

log = get_logger()

_GIT_TIMEOUT_SECONDS = 2.0


def detect_put_version(project_root: Path | None = None, override: PutVersionInfo | None = None) -> PutVersionInfo:
    """Detect the program-under-test metadata.

    :param project_root: Directory to walk up from when searching for project
        metadata.  Defaults to :func:`Path.cwd`.
    :param override: If supplied, returned verbatim with ``source="override"``.
    :return: A populated :class:`PutVersionInfo`.  Fields that could not be
        determined are ``None``; callers must tolerate that.
    """
    if override is not None:
        return override

    root = (project_root or Path.cwd()).resolve()

    name, version, author, source = None, None, None, "unknown"

    pyproject_name, pyproject_version, pyproject_author, pyproject_root = _read_pyproject(root)
    if pyproject_name is not None or pyproject_version is not None:
        name, version, source = pyproject_name, pyproject_version, "pyproject"
        author = pyproject_author
        if pyproject_root is not None:
            root = pyproject_root

    if version is None:
        cfg_name, cfg_version, cfg_author, cfg_root = _read_setup_cfg(root)
        if cfg_name is not None or cfg_version is not None:
            name = name or cfg_name
            version = cfg_version
            author = author or cfg_author
            source = "setup.cfg"
            if cfg_root is not None:
                root = cfg_root

    if version is None and name:
        metadata_version = _importlib_metadata_version(name)
        if metadata_version is not None:
            version = metadata_version
            source = "importlib.metadata"

    git_describe, git_sha, git_branch, git_dirty = _collect_git_info(root)

    return PutVersionInfo(
        name=name,
        version=version,
        source=source,
        git_describe=git_describe,
        git_sha=git_sha,
        git_branch=git_branch,
        git_dirty=git_dirty,
        project_root=str(root),
        author=author,
    )


def _walk_up_for_file(start: Path, filename: str) -> Path | None:
    """Walk upward from *start* looking for *filename*.  Returns the containing directory or ``None``."""
    current = start
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        candidate = current / filename
        if candidate.is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _read_pyproject(start: Path) -> tuple[str | None, str | None, str | None, Path | None]:
    """Return ``(name, version_or_None_if_dynamic, author, project_root)`` from the nearest ``pyproject.toml``."""
    project_dir = _walk_up_for_file(start, "pyproject.toml")
    if project_dir is None:
        return None, None, None, None
    try:
        with open(project_dir / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.debug(f"could not parse pyproject.toml at {project_dir}: {e}")
        return None, None, None, project_dir

    project = data.get("project", {}) or {}
    name = project.get("name")
    version = project.get("version")
    # Treat a pyproject that marks "version" as dynamic as version=None (fall through to importlib.metadata).
    dynamic = project.get("dynamic") or []
    if "version" in dynamic:
        version = None
    if not isinstance(name, str):
        name = None
    if not isinstance(version, str):
        version = None
    authors = project.get("authors") or []
    author: str | None = None
    if isinstance(authors, list):
        for entry in authors:
            if isinstance(entry, dict):
                candidate = entry.get("name") or entry.get("email")
                if isinstance(candidate, str) and candidate:
                    author = candidate
                    break
    return name, version, author, project_dir


def _read_setup_cfg(start: Path) -> tuple[str | None, str | None, str | None, Path | None]:
    """Return ``(name, version, author, project_root)`` from the nearest ``setup.cfg``."""
    project_dir = _walk_up_for_file(start, "setup.cfg")
    if project_dir is None:
        return None, None, None, None
    parser = configparser.ConfigParser()
    try:
        parser.read(project_dir / "setup.cfg", encoding="utf-8")
    except (OSError, configparser.Error) as e:
        log.debug(f"could not parse setup.cfg at {project_dir}: {e}")
        return None, None, None, project_dir
    if not parser.has_section("metadata"):
        return None, None, None, project_dir
    name = parser.get("metadata", "name", fallback=None)
    version = parser.get("metadata", "version", fallback=None)
    # setup.cfg can reference a file or attr for version; if it starts with "file:" / "attr:"
    # we can't resolve it without executing setup.py, so treat as missing.
    if version and version.strip().startswith(("file:", "attr:")):
        version = None
    author = parser.get("metadata", "author", fallback=None) or parser.get("metadata", "author_email", fallback=None)
    return name, version, author, project_dir


def _importlib_metadata_version(name: str) -> str | None:
    """Return the installed version of *name* via :mod:`importlib.metadata`, or ``None``."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
    except Exception as e:
        log.debug(f"importlib.metadata lookup failed for {name!r}: {e}")
        return None


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run ``git <args>`` in *cwd*.  Returns stripped stdout or ``None`` on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        log.debug(f"git {args} failed in {cwd}: {e}")
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out if out else None


def _is_git_repo(project_root: Path) -> bool:
    """Return True if *project_root* is inside a git working tree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _collect_git_info(project_root: Path) -> tuple[str | None, str | None, str | None, bool | None]:
    """Return ``(describe, short_sha, branch, dirty)`` for the git repo at *project_root*.

    All four values are ``None`` when git is unavailable or the directory is not a git repo.
    """
    if not _is_git_repo(project_root):
        return None, None, None, None

    describe = _run_git(["describe", "--tags", "--always", "--dirty"], project_root)
    sha = _run_git(["rev-parse", "--short", "HEAD"], project_root)
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root)
    # `git status --porcelain` returns empty string on clean, non-empty on dirty.
    # _run_git returns None for empty stdout, so None here means clean (given we got this far).
    status = _run_git(["status", "--porcelain"], project_root)
    dirty = bool(status)
    return describe, sha, branch, dirty
