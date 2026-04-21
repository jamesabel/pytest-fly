"""Tests for :mod:`pytest_fly.pytest_runner.ordering`."""

from pytest_fly.interfaces import OrderingAspect, ScheduledTest
from pytest_fly.pytest_runner.ordering import (
    PRIOR_DATA_ASPECTS,
    OrderingContext,
    apply_ordering_aspects,
)


def _t(name: str, singleton: bool = False, duration: float | None = None, coverage: float | None = None) -> ScheduledTest:
    return ScheduledTest(node_id=name, singleton=singleton, duration=duration, coverage=coverage)


def test_no_aspects_alphabetical_baseline():
    tests = [_t("b"), _t("a"), _t("c")]
    result = apply_ordering_aspects(tests, [], OrderingContext())
    assert [t.node_id for t in result] == ["a", "b", "c"]


def test_singletons_always_last_without_aspects():
    tests = [_t("singleton_z", singleton=True), _t("normal_b"), _t("normal_a"), _t("singleton_a", singleton=True)]
    result = apply_ordering_aspects(tests, [], OrderingContext())
    assert [t.node_id for t in result] == ["normal_a", "normal_b", "singleton_a", "singleton_z"]


def test_failed_first():
    tests = [_t("pass_a"), _t("fail_b"), _t("pass_c")]
    ctx = OrderingContext(failed_names={"fail_b"})
    result = apply_ordering_aspects(tests, [OrderingAspect.FAILED_FIRST], ctx)
    assert result[0].node_id == "fail_b"


def test_never_run_first():
    tests = [_t("old"), _t("new"), _t("ancient")]
    ctx = OrderingContext(ever_run_names={"old", "ancient"})
    result = apply_ordering_aspects(tests, [OrderingAspect.NEVER_RUN_FIRST], ctx)
    assert result[0].node_id == "new"


def test_longest_prior_first():
    tests = [_t("a"), _t("b"), _t("c")]
    ctx = OrderingContext(prior_durations={"a": 10.0, "b": 1.0, "c": 5.0})
    result = apply_ordering_aspects(tests, [OrderingAspect.LONGEST_PRIOR_FIRST], ctx)
    assert [t.node_id for t in result] == ["a", "c", "b"]


def test_longest_prior_first_missing_duration_lands_last():
    tests = [_t("a"), _t("no_data"), _t("b")]
    ctx = OrderingContext(prior_durations={"a": 5.0, "b": 2.0})
    result = apply_ordering_aspects(tests, [OrderingAspect.LONGEST_PRIOR_FIRST], ctx)
    # no_data sorts last in the longest-first bucket; ties broken by alphabetical baseline.
    assert result[-1].node_id == "no_data"
    assert result[0].node_id == "a"


def test_coverage_efficiency():
    # fast: 0.8 coverage / 2s = 0.4 lines/s
    # slow: 0.8 coverage / 10s = 0.08 lines/s
    # nodata: both None -> sorts last
    tests = [_t("slow", duration=10.0, coverage=0.8), _t("fast", duration=2.0, coverage=0.8), _t("nodata")]
    result = apply_ordering_aspects(tests, [OrderingAspect.COVERAGE_EFFICIENCY], OrderingContext())
    assert [t.node_id for t in result] == ["fast", "slow", "nodata"]


def test_priority_order_matters():
    """With both failed and never-run aspects, the first one in the list dominates ties."""
    # failing_new has failed AND never run.
    # passing_new has not failed, and never run.
    # failing_old has failed, and has been run.
    tests = [_t("failing_old"), _t("passing_new"), _t("failing_new")]
    ctx = OrderingContext(failed_names={"failing_old", "failing_new"}, ever_run_names={"failing_old"})

    # Failed-first dominates -> failing_old/failing_new come before passing_new.
    result = apply_ordering_aspects(tests, [OrderingAspect.FAILED_FIRST, OrderingAspect.NEVER_RUN_FIRST], ctx)
    # Among the two failed: failing_new is never-run so comes first.
    assert result[0].node_id == "failing_new"
    assert result[1].node_id == "failing_old"
    assert result[2].node_id == "passing_new"

    # Swap: never-run-first dominates.
    result2 = apply_ordering_aspects(tests, [OrderingAspect.NEVER_RUN_FIRST, OrderingAspect.FAILED_FIRST], ctx)
    # failing_new + passing_new are both never-run; within that bucket failed_first orders failing_new first.
    assert result2[0].node_id == "failing_new"
    assert result2[1].node_id == "passing_new"
    assert result2[2].node_id == "failing_old"


def test_singleton_invariant_across_aspects():
    """Singleton tests sort last regardless of the aspect chain."""
    tests = [_t("normal_b"), _t("singleton_a", singleton=True), _t("normal_a")]
    ctx = OrderingContext(failed_names={"singleton_a"}, ever_run_names=set(), prior_durations={"singleton_a": 100.0})
    aspects = [OrderingAspect.FAILED_FIRST, OrderingAspect.LONGEST_PRIOR_FIRST, OrderingAspect.NEVER_RUN_FIRST]
    result = apply_ordering_aspects(tests, aspects, ctx)
    assert result[-1].node_id == "singleton_a"


def test_prior_data_aspects_set():
    assert OrderingAspect.FAILED_FIRST in PRIOR_DATA_ASPECTS
    assert OrderingAspect.LONGEST_PRIOR_FIRST in PRIOR_DATA_ASPECTS
    assert OrderingAspect.COVERAGE_EFFICIENCY in PRIOR_DATA_ASPECTS
    assert OrderingAspect.NEVER_RUN_FIRST not in PRIOR_DATA_ASPECTS
