"""Tests for paths.get_default_data_dir."""

from pathlib import Path
from tempfile import TemporaryDirectory

from pytest_fly.const import PYTEST_FLY_DATA_DIR_STRING
from pytest_fly.paths import get_default_data_dir


def test_env_var_overrides_default(monkeypatch):
    with TemporaryDirectory() as tmp:
        override = Path(tmp, "custom_data")
        monkeypatch.setenv(PYTEST_FLY_DATA_DIR_STRING, str(override))
        get_default_data_dir.cache_clear()

        result = get_default_data_dir()

        assert result == override
        assert result.is_dir()


def test_default_when_env_var_missing(monkeypatch):
    monkeypatch.delenv(PYTEST_FLY_DATA_DIR_STRING, raising=False)
    get_default_data_dir.cache_clear()

    result = get_default_data_dir()

    assert result.is_dir()
