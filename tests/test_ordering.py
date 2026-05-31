"""Direct tests for the private :func:`_key_for` sort-key helper in the ordering module.

The public :func:`apply_ordering_aspects` is covered by ``test_ordering_aspects.py``;
this file exercises the per-aspect key edge cases (missing prior data, the
coverage-efficiency fallback, and the unknown-aspect guard).
"""

import math

import pytest

from pytest_fly.interfaces import OrderingAspect, ScheduledTest
from pytest_fly.pytest_runner.ordering import OrderingContext, _key_for


def _t(name, singleton=False, duration=None, coverage=None):
    return ScheduledTest(node_id=name, singleton=singleton, duration=duration, coverage=coverage)


def test_key_for_failed_first():
    ctx = OrderingContext(failed_names={"a"})
    assert _key_for(OrderingAspect.FAILED_FIRST, _t("a"), ctx) == 0.0
    assert _key_for(OrderingAspect.FAILED_FIRST, _t("b"), ctx) == 1.0


def test_key_for_never_run_first():
    ctx = OrderingContext(ever_run_names={"a"})
    assert _key_for(OrderingAspect.NEVER_RUN_FIRST, _t("a"), ctx) == 1.0  # has run -> later
    assert _key_for(OrderingAspect.NEVER_RUN_FIRST, _t("b"), ctx) == 0.0  # never run -> first


def test_key_for_longest_prior_first():
    ctx = OrderingContext(prior_durations={"a": 9.0})
    assert _key_for(OrderingAspect.LONGEST_PRIOR_FIRST, _t("a"), ctx) == -9.0
    # Missing prior duration -> 0.0 (sorts after tests that have a measured duration).
    assert _key_for(OrderingAspect.LONGEST_PRIOR_FIRST, _t("b"), ctx) == 0.0


def test_key_for_coverage_efficiency_with_data():
    # lines_per_second = coverage / duration = 0.5 / 2 = 0.25; negated so higher sorts first.
    key = _key_for(OrderingAspect.COVERAGE_EFFICIENCY, _t("a", duration=2.0, coverage=0.5), OrderingContext())
    assert key == -0.25


def test_key_for_coverage_efficiency_missing_data_is_inf():
    # No duration/coverage -> efficiency unknown -> sorts last.
    key = _key_for(OrderingAspect.COVERAGE_EFFICIENCY, _t("a"), OrderingContext())
    assert key == math.inf


def test_key_for_unknown_aspect_raises():
    with pytest.raises(ValueError):
        _key_for("not_an_aspect", _t("a"), OrderingContext())
