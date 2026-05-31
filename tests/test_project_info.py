"""Tests for :mod:`pytest_fly.gui.about_tab.project_info`."""

from importlib import metadata

from pytest_fly.gui.about_tab import project_info
from pytest_fly.gui.about_tab.project_info import (
    ProjectInfo,
    _from_installed_metadata,
    _from_pyproject,
    _license_from_classifiers,
    get_project_info,
)


def test_license_from_classifiers_finds_license():
    """Returns the tail of the first 'License ::' classifier."""
    classifiers = ["Programming Language :: Python", "License :: OSI Approved :: MIT License"]
    assert _license_from_classifiers(classifiers) == "MIT License"


def test_license_from_classifiers_none_when_absent():
    """Returns None when there is no license classifier."""
    assert _license_from_classifiers(["Topic :: Testing"]) is None
    assert _license_from_classifiers(None) is None


def test_from_pyproject_reads_repo_metadata():
    """Walking up to the repo pyproject.toml yields pytest-fly's real metadata."""
    info = _from_pyproject()
    assert info is not None
    assert info.application_name == "pytest-fly"
    assert info.version != "Unknown"
    assert "MIT" in info.license
    assert "github.com/jamesabel/pytest-fly" in info.home_url
    assert "github.com/jamesabel/pytest-fly" in info.repository_url


def test_from_installed_metadata_none_when_not_installed(monkeypatch):
    """A missing package surfaces as None rather than raising."""

    def _raise(_name):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(project_info.metadata, "metadata", _raise)
    assert _from_installed_metadata() is None


class _FakeMeta:
    """Minimal stand-in for importlib.metadata's Message object."""

    def __init__(self, scalars, multi):
        self._scalars = scalars
        self._multi = multi

    def get(self, key, default=None):
        return self._scalars.get(key, default)

    def get_all(self, key):
        return self._multi.get(key)


def test_from_installed_metadata_parses_fields(monkeypatch):
    """The installed-metadata path extracts name, version, author, license, and URLs."""
    fake = _FakeMeta(
        scalars={"Name": "pytest-fly", "Version": "9.9.9", "Author-email": "Jane <jane@example.com>", "Summary": "a runner"},
        multi={
            "Classifier": ["License :: OSI Approved :: MIT License"],
            "Project-URL": ["Homepage, https://example.com/home", "Repository, https://example.com/repo"],
        },
    )
    monkeypatch.setattr(project_info.metadata, "metadata", lambda _name: fake)

    info = _from_installed_metadata()
    assert info is not None
    assert info.application_name == "pytest-fly"
    assert info.version == "9.9.9"
    assert "jane@example.com" in info.author
    assert info.description == "a runner"
    assert info.license == "MIT License"
    assert info.home_url == "https://example.com/home"
    assert info.repository_url == "https://example.com/repo"


def test_from_installed_metadata_home_page_fallback(monkeypatch):
    """When only a Home-page scalar is present, it fills home_url and then repository_url."""
    fake = _FakeMeta(
        scalars={"Name": "pkg", "Version": "1.0", "Author": "A", "Home-page": "https://example.com/hp"},
        multi={},
    )
    monkeypatch.setattr(project_info.metadata, "metadata", lambda _name: fake)
    info = _from_installed_metadata()
    assert info.home_url == "https://example.com/hp"
    assert info.repository_url == "https://example.com/hp"  # cross-filled from home


def test_from_installed_metadata_repository_only_fills_home(monkeypatch):
    """When only a Repository URL is present, home_url is cross-filled from it."""
    fake = _FakeMeta(
        scalars={"Name": "pkg", "Version": "1.0", "Author": "A"},
        multi={"Project-URL": ["Repository, https://example.com/repo"]},
    )
    monkeypatch.setattr(project_info.metadata, "metadata", lambda _name: fake)
    info = _from_installed_metadata()
    assert info.repository_url == "https://example.com/repo"
    assert info.home_url == "https://example.com/repo"  # cross-filled from repository


def test_get_project_info_falls_back_to_installed_metadata(monkeypatch):
    """When pyproject yields no usable version, get_project_info uses installed metadata."""
    monkeypatch.setattr(project_info, "_from_pyproject", lambda: None)
    fake = _FakeMeta(scalars={"Name": "pytest-fly", "Version": "1.0.0", "Author": "Jane"}, multi={})
    monkeypatch.setattr(project_info.metadata, "metadata", lambda _name: fake)

    get_project_info.cache_clear()
    info = get_project_info()
    get_project_info.cache_clear()  # don't leak the patched value to other tests
    assert info.version == "1.0.0"


def test_get_project_info_is_populated():
    """The public accessor returns a ProjectInfo with a real version."""
    get_project_info.cache_clear()
    info = get_project_info()
    assert isinstance(info, ProjectInfo)
    assert info.application_name == "pytest-fly"
    assert info.version != "Unknown"


def test_project_info_str():
    """__str__ renders name, version, and author on separate lines."""
    info = ProjectInfo(application_name="demo", author="Jane", version="1.2.3")
    assert str(info) == "demo\n1.2.3\nJane"
