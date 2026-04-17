"""Tests for :mod:`pytest_fly.put_version` — program-under-test version detection."""

import subprocess
from pathlib import Path

import pytest

from pytest_fly.interfaces import PutVersionInfo
from pytest_fly.put_version import detect_put_version


def _write_pyproject(tmp_path: Path, body: str) -> None:
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=2, check=False)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _init_git_repo(path: Path, *, commit: bool = True) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), check=True)
    # Force master so the branch name is deterministic across git versions.
    subprocess.run(["git", "checkout", "-q", "-b", "master"], cwd=str(path), check=True)
    if commit:
        subprocess.run(["git", "add", "-A"], cwd=str(path), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(path), check=True)


def test_pyproject_static_version(tmp_path):
    _write_pyproject(tmp_path, '[project]\nname = "widget"\nversion = "1.2.3"\n')
    info = detect_put_version(tmp_path)
    assert info.name == "widget"
    assert info.version == "1.2.3"
    assert info.source == "pyproject"


def test_pyproject_dynamic_version_without_install(tmp_path):
    """Dynamic version and the package isn't installed — version should be None but name preserved."""
    _write_pyproject(
        tmp_path,
        '[project]\nname = "definitely-not-installed-pkg-xyz-pytest-fly-test"\ndynamic = ["version"]\n',
    )
    info = detect_put_version(tmp_path)
    assert info.name == "definitely-not-installed-pkg-xyz-pytest-fly-test"
    assert info.version is None
    # Source remains "pyproject" because the name came from there, even though the version fell through.
    assert info.source == "pyproject"


def test_pyproject_dynamic_version_with_installed_package(tmp_path):
    """Dynamic version falls back to importlib.metadata when the package is installed (pytest is always installed)."""
    _write_pyproject(tmp_path, '[project]\nname = "pytest"\ndynamic = ["version"]\n')
    info = detect_put_version(tmp_path)
    assert info.name == "pytest"
    assert info.version is not None  # importlib.metadata resolved pytest
    assert info.source == "importlib.metadata"


def test_setup_cfg_only(tmp_path):
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = sample\nversion = 0.9.0\n", encoding="utf-8")
    info = detect_put_version(tmp_path)
    assert info.name == "sample"
    assert info.version == "0.9.0"
    assert info.source == "setup.cfg"


def test_setup_cfg_file_reference_is_ignored(tmp_path):
    """setup.cfg version of `file:` or `attr:` can't be resolved without executing setup.py — treated as missing."""
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = sample\nversion = file: VERSION\n", encoding="utf-8")
    info = detect_put_version(tmp_path)
    assert info.name == "sample"
    assert info.version is None


def test_no_metadata_no_git_unknown(tmp_path):
    info = detect_put_version(tmp_path)
    assert info.name is None
    assert info.version is None
    assert info.source == "unknown"
    assert info.git_sha is None
    assert info.git_dirty is None


def test_override_returned_verbatim(tmp_path):
    override = PutVersionInfo(
        name="from-override",
        version="9.9.9",
        source="override",
        git_describe=None,
        git_sha=None,
        git_branch=None,
        git_dirty=None,
        project_root=str(tmp_path),
    )
    info = detect_put_version(tmp_path, override=override)
    assert info is override


@pytest.mark.skipif(not _git_available(), reason="git is not available")
def test_git_clean_tree(tmp_path):
    _write_pyproject(tmp_path, '[project]\nname = "gitpkg"\nversion = "0.1.0"\n')
    _init_git_repo(tmp_path, commit=True)
    info = detect_put_version(tmp_path)
    assert info.name == "gitpkg"
    assert info.version == "0.1.0"
    assert info.git_sha is not None
    assert info.git_dirty is False
    # fingerprint should encode the clean state
    assert "clean" in info.fingerprint()


@pytest.mark.skipif(not _git_available(), reason="git is not available")
def test_git_dirty_changes_fingerprint(tmp_path):
    _write_pyproject(tmp_path, '[project]\nname = "gitpkg"\nversion = "0.1.0"\n')
    _init_git_repo(tmp_path, commit=True)
    clean = detect_put_version(tmp_path)

    # Make the tree dirty.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "gitpkg"\nversion = "0.1.0"\n# dirty edit\n', encoding="utf-8")
    dirty = detect_put_version(tmp_path)

    assert clean.git_dirty is False
    assert dirty.git_dirty is True
    assert clean.fingerprint() != dirty.fingerprint()


def test_short_label_includes_name_and_version():
    info = PutVersionInfo(
        name="widget",
        version="1.2.3",
        source="pyproject",
        git_describe=None,
        git_sha="abc1234",
        git_branch="main",
        git_dirty=False,
        project_root="/some/path",
    )
    assert info.short_label() == "widget 1.2.3 (abc1234)"


def test_short_label_with_dirty_suffix():
    info = PutVersionInfo(
        name="widget",
        version="1.2.3",
        source="pyproject",
        git_describe=None,
        git_sha="abc1234",
        git_branch="main",
        git_dirty=True,
        project_root="/some/path",
    )
    assert info.short_label() == "widget 1.2.3 (abc1234-dirty)"


def test_short_label_unknown_fallback():
    info = PutVersionInfo(
        name=None,
        version=None,
        source="unknown",
        git_describe=None,
        git_sha=None,
        git_branch=None,
        git_dirty=None,
        project_root="/some/path",
    )
    assert info.short_label() == "unknown ?"


def test_fingerprint_is_deterministic():
    a = PutVersionInfo("p", "1", "pyproject", None, "abc", None, False, "/")
    b = PutVersionInfo("p", "1", "pyproject", None, "abc", None, False, "/")
    assert a.fingerprint() == b.fingerprint()

    c = PutVersionInfo("p", "2", "pyproject", None, "abc", None, False, "/")
    assert a.fingerprint() != c.fingerprint()
