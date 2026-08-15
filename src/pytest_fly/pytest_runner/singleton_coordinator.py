"""
Singleton-vs-parallel execution coordinator — a standalone threading primitive.

Extracted from :mod:`pytest_runner` so the worker-scheduling policy is separated from
the orchestration code that uses it.
"""

from threading import Condition


class SingletonCoordinator:
    """
    Serializes singleton tests against all other worker threads.

    A *singleton* must run exclusively — no other workers executing.  A
    *normal* test may run in parallel with any number of other normal tests.

    The slot counter and exclusion flag live under a single
    :class:`threading.Condition` so check-and-claim is atomic.  Waiting
    singletons block new normal acquisitions, preventing starvation.

    Acquires are poll-interruptible via *stop_predicate* so a worker can
    abandon its wait when a stop has been requested.
    """

    def __init__(self) -> None:
        self._cond = Condition()
        self._active = 0
        self._singleton_running = False
        self._singleton_waiters = 0

    def acquire_normal(self, stop_predicate, poll_interval: float) -> bool:
        """Claim a non-exclusive slot.  Returns ``False`` if *stop_predicate* went true while waiting."""
        with self._cond:
            while self._singleton_running or self._singleton_waiters > 0:
                if stop_predicate():
                    return False
                self._cond.wait(timeout=poll_interval)
            self._active += 1
            return True

    def release_normal(self) -> None:
        """Release a slot claimed with :meth:`acquire_normal`."""
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def acquire_singleton(self, stop_predicate, poll_interval: float) -> bool:
        """Claim exclusive access.  Returns ``False`` if *stop_predicate* went true while waiting."""
        with self._cond:
            self._singleton_waiters += 1
            try:
                while self._singleton_running or self._active > 0:
                    if stop_predicate():
                        return False
                    self._cond.wait(timeout=poll_interval)
                self._singleton_running = True
                self._active += 1
                return True
            finally:
                self._singleton_waiters -= 1
                if self._singleton_waiters == 0:
                    self._cond.notify_all()

    def release_singleton(self) -> None:
        """Release the exclusive slot claimed with :meth:`acquire_singleton`."""
        with self._cond:
            self._singleton_running = False
            self._active -= 1
            self._cond.notify_all()

    def active_slot_count(self) -> int:
        """Return the number of in-flight slots (normal + singleton).

        ``0`` means nothing is currently running, which the admission gate uses for
        its min-1 forward-progress guarantee: a heavy test is always admitted when no
        other test is in flight, so the suite can never deadlock behind the gate.
        """
        with self._cond:
            return self._active


# Backward-compatible alias for the previous private name.
_SingletonCoordinator = SingletonCoordinator
