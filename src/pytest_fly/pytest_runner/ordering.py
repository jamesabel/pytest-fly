"""
Pure, Qt-free test-ordering helper.

The Configuration tab lets the user choose which :class:`OrderingAspect` values
are enabled and in what priority order.  :func:`apply_ordering_aspects` takes
that priority list and produces a sorted list of :class:`ScheduledTest`.

Singletons always sort last regardless of aspects — they hold a process
exclusively, so running them at the end minimises idle workers.
"""

import math
from dataclasses import dataclass, field

from ..interfaces import OrderingAspect, ScheduledTest, lines_per_second


@dataclass(frozen=True)
class OrderingContext:
    """Data sources the aspect key functions read from."""

    failed_names: set[str] = field(default_factory=set)  # node_ids of tests that failed in the most recent run
    ever_run_names: set[str] = field(default_factory=set)  # node_ids with any DB record across any PUT version
    prior_durations: dict[str, float] = field(default_factory=dict)  # node_id -> duration (seconds) from the most recent passing run
    per_test_coverage: dict[str, float] = field(default_factory=dict)  # node_id -> fraction covered (0..1); unused for keying but preserved for completeness


def _key_for(aspect: OrderingAspect, test: ScheduledTest, ctx: OrderingContext) -> float:
    """Return a sort key for *test* under *aspect*.  Lower = earlier."""
    if aspect is OrderingAspect.FAILED_FIRST:
        return 0.0 if test.node_id in ctx.failed_names else 1.0
    if aspect is OrderingAspect.NEVER_RUN_FIRST:
        return 0.0 if test.node_id not in ctx.ever_run_names else 1.0
    if aspect is OrderingAspect.LONGEST_PRIOR_FIRST:
        # Negate so larger duration sorts earlier.  Missing -> 0 -> sorts last among its peers.
        return -ctx.prior_durations.get(test.node_id, 0.0)
    if aspect is OrderingAspect.COVERAGE_EFFICIENCY:
        lps = lines_per_second(test.duration, test.coverage)
        if lps is None:
            return math.inf
        return -lps
    raise ValueError(f"Unknown ordering aspect: {aspect!r}")


def apply_ordering_aspects(
    tests: list[ScheduledTest],
    aspects: list[OrderingAspect],
    ctx: OrderingContext,
) -> list[ScheduledTest]:
    """Order *tests* according to *aspects* (higher priority aspects dominate).

    Stable-sorts the list repeatedly: first the lowest-priority enabled aspect,
    last the highest-priority one.  Python's ``sorted`` is stable, so aspects
    later in this chain override earlier ones while preserving the relative
    order established by earlier sorts for ties.

    The outermost bucket in every key is ``test.singleton`` — ``True`` sorts
    last — so singletons always run at the end.

    :param tests: Tests to order.
    :param aspects: Enabled aspects in priority order (index 0 = highest priority).
        Callers are expected to have already filtered out disabled aspects.
        Aspects that read prior-run data gracefully produce tie keys when no data
        exists, so they are safe to include in RESTART mode too.
    :param ctx: Supporting data for the aspect key functions.
    :return: A new list ordered for execution.
    """
    # Start from a stable alphabetical baseline so order is deterministic when
    # no aspects are enabled or when every aspect produces equal keys.
    ordered = sorted(tests, key=lambda t: (t.singleton, t.node_id))
    # Apply aspects in reverse priority order so the highest-priority aspect
    # is the final (and therefore dominant) sort pass.
    for aspect in reversed(aspects):
        ordered = sorted(ordered, key=lambda t, a=aspect: (t.singleton, _key_for(a, t, ctx)))
    return ordered
