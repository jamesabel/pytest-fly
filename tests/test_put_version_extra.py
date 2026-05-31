"""Additional coverage for the metadata-parsing branches of :mod:`pytest_fly.put_version`."""

from pytest_fly.put_version import detect_put_version


def _write(tmp_path, name, body):
    (tmp_path / name).write_text(body, encoding="utf-8")


def test_pyproject_malformed_toml(tmp_path):
    """A pyproject that won't parse leaves name/version unset (parse error swallowed)."""
    _write(tmp_path, "pyproject.toml", "this is not = valid = toml ===\n[[[")
    info = detect_put_version(tmp_path)
    assert info.name is None
    assert info.version is None


def test_pyproject_non_string_name_is_dropped(tmp_path):
    """A non-string name is coerced to None while a valid version is still read."""
    _write(tmp_path, "pyproject.toml", '[project]\nname = 123\nversion = "1.0"\n')
    info = detect_put_version(tmp_path)
    assert info.name is None
    assert info.version == "1.0"
    assert info.source == "pyproject"


def test_pyproject_author_extracted(tmp_path):
    """The first author with a name is captured."""
    _write(tmp_path, "pyproject.toml", '[project]\nname = "w"\nversion = "1.0"\nauthors = [{name = "Jane Doe"}]\n')
    info = detect_put_version(tmp_path)
    assert info.author == "Jane Doe"


def test_setup_cfg_malformed(tmp_path):
    """A setup.cfg with no section header fails to parse and yields no metadata."""
    _write(tmp_path, "setup.cfg", "name = orphan\nversion = 1.0\n")  # missing [section] header
    info = detect_put_version(tmp_path)
    assert info.name is None
    assert info.version is None


def test_setup_cfg_without_metadata_section(tmp_path):
    """A valid setup.cfg lacking a [metadata] section yields no name/version."""
    _write(tmp_path, "setup.cfg", "[options]\npackages = find:\n")
    info = detect_put_version(tmp_path)
    assert info.name is None
    assert info.version is None
