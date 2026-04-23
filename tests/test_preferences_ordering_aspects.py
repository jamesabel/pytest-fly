"""Tests for the PrefOrderedSet-backed ordering-aspect persistence helpers."""

import pytest
from pref import pref as pref_mod

from pytest_fly.interfaces import OrderingAspect
from pytest_fly.preferences import (
    _default_ordering_aspect_seed,
    get_ordering_aspects_ordered,
    get_ordering_aspects_set,
    get_pref,
    reset_pref_cache,
    set_ordering_aspects_ordered,
)


@pytest.fixture
def isolated_prefs(tmp_path, monkeypatch):
    """Redirect pref's SQLite storage to a unique tmp dir for each test.

    The pref library resolves its storage via ``appdirs.user_config_dir`` at
    instantiation time, so patching it on the ``pref.pref`` module is enough
    to send every pref (including :class:`PrefOrderedSet`) into tmp_path.
    Also drops :func:`get_pref`'s in-process cache before and after the test
    so a stale instance from prior code paths can't bleed in.
    """
    reset_pref_cache()
    monkeypatch.setattr(pref_mod.appdirs, "user_config_dir", lambda *a, **kw: str(tmp_path))
    yield tmp_path
    reset_pref_cache()


def test_first_call_seeds_defaults(isolated_prefs):
    assert not get_pref().ordering_aspects_seeded
    assert get_ordering_aspects_ordered() == _default_ordering_aspect_seed
    assert get_pref().ordering_aspects_seeded


def test_round_trip(isolated_prefs):
    # Prime the seeded flag so we're exercising a real write, not the seed path.
    get_pref().ordering_aspects_seeded = True
    new_order = [OrderingAspect.COVERAGE_EFFICIENCY, OrderingAspect.FAILED_FIRST]
    set_ordering_aspects_ordered(new_order)
    assert get_ordering_aspects_ordered() == new_order


def test_unknown_value_skipped(isolated_prefs):
    get_pref().ordering_aspects_seeded = True
    aspect_set = get_ordering_aspects_set()
    aspect_set.set([OrderingAspect.FAILED_FIRST.value, "not_a_real_aspect", OrderingAspect.COVERAGE_EFFICIENCY.value])
    assert get_ordering_aspects_ordered() == [OrderingAspect.FAILED_FIRST, OrderingAspect.COVERAGE_EFFICIENCY]


def test_empty_set_stays_empty_after_explicit_clear(isolated_prefs):
    # First call seeds defaults.
    get_ordering_aspects_ordered()
    # User deliberately clears everything.
    set_ordering_aspects_ordered([])
    # Subsequent reads return empty — no re-seeding.
    assert get_ordering_aspects_ordered() == []
    assert get_pref().ordering_aspects_seeded
