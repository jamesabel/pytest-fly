"""Reads pytest-fly's own project metadata (name, version, author, license, URLs)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib import metadata
from pathlib import Path

_PACKAGE_NAME = "pytest-fly"
_UNKNOWN = "Unknown"


@dataclass(frozen=True)
class ProjectInfo:
    application_name: str
    author: str
    version: str
    license: str = _UNKNOWN
    description: str = _UNKNOWN
    home_url: str = _UNKNOWN
    repository_url: str = _UNKNOWN

    def __str__(self):
        return f"{self.application_name}\n{self.version}\n{self.author}"


def _license_from_classifiers(classifiers) -> str | None:
    for classifier in classifiers or []:
        if isinstance(classifier, str) and classifier.startswith("License ::"):
            tail = classifier.split("::")[-1].strip()
            if tail:
                return tail
    return None


def _from_installed_metadata() -> ProjectInfo | None:
    try:
        meta = metadata.metadata(_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return None

    name = meta.get("Name") or _UNKNOWN
    version = meta.get("Version") or _UNKNOWN
    author = meta.get("Author") or meta.get("Author-email") or _UNKNOWN
    description = meta.get("Summary") or _UNKNOWN

    license_name = _license_from_classifiers(meta.get_all("Classifier")) or meta.get("License-Expression") or meta.get("License") or _UNKNOWN
    # A License field copied from a file can be many lines; keep the first non-empty line.
    if license_name and license_name != _UNKNOWN:
        for line in license_name.splitlines():
            stripped = line.strip()
            if stripped:
                license_name = stripped
                break

    home_url = _UNKNOWN
    repository_url = _UNKNOWN
    for value in meta.get_all("Project-URL") or []:
        label, _, url = value.partition(",")
        key = label.strip().lower()
        url = url.strip()
        if key in ("home", "homepage") and home_url == _UNKNOWN:
            home_url = url
        elif key in ("repository", "source") and repository_url == _UNKNOWN:
            repository_url = url
    home_page = meta.get("Home-page")
    if home_url == _UNKNOWN and home_page:
        home_url = home_page
    if repository_url == _UNKNOWN and home_url != _UNKNOWN:
        repository_url = home_url
    if home_url == _UNKNOWN and repository_url != _UNKNOWN:
        home_url = repository_url

    return ProjectInfo(
        application_name=name,
        author=author,
        version=version,
        license=license_name,
        description=description,
        home_url=home_url,
        repository_url=repository_url,
    )


def _from_pyproject() -> ProjectInfo | None:
    pyproject_dir = Path(__file__).resolve().parent
    pyproject_data = None
    while True:
        pyproject_path = pyproject_dir / "pyproject.toml"
        if pyproject_path.is_file():
            try:
                with open(pyproject_path, "rb") as file:
                    pyproject_data = tomllib.load(file)
            except (OSError, tomllib.TOMLDecodeError):
                return None
            break
        parent = pyproject_dir.parent
        if parent == pyproject_dir:
            return None
        pyproject_dir = parent

    project = pyproject_data.get("project", {}) or {}
    name = project.get("name", _UNKNOWN)
    version = project.get("version", _UNKNOWN)
    description = project.get("description", _UNKNOWN)
    authors = project.get("authors", []) or []
    author = authors[0].get("name", _UNKNOWN) if authors else _UNKNOWN

    license_name = _license_from_classifiers(project.get("classifiers"))
    if not license_name:
        license_obj = project.get("license")
        if isinstance(license_obj, str):
            license_name = license_obj
        elif isinstance(license_obj, dict) and "text" in license_obj:
            license_name = license_obj["text"]
    if not license_name:
        license_name = _UNKNOWN

    urls = project.get("urls", {}) or {}
    home_url = urls.get("Home") or urls.get("Homepage") or _UNKNOWN
    repository_url = urls.get("Repository") or urls.get("Source") or home_url

    return ProjectInfo(
        application_name=name,
        author=author,
        version=version,
        license=license_name,
        description=description,
        home_url=home_url,
        repository_url=repository_url,
    )


@cache
def get_project_info() -> ProjectInfo:
    # Prefer pyproject.toml when running from a source checkout so the version
    # matches the code actually executing; fall back to installed metadata for
    # wheel installs where pyproject.toml isn't shipped.
    info = _from_pyproject()
    if info is not None and info.version != _UNKNOWN:
        return info
    fallback = _from_installed_metadata()
    if fallback is not None:
        return fallback
    if info is not None:
        return info
    return ProjectInfo(_UNKNOWN, _UNKNOWN, _UNKNOWN)
