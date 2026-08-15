"""
Shared base for run-scoped monitor daemons (the stall watchdog and the resource guard).

Both monitors have the same lifecycle: a daemon thread that evaluates a ``tick()`` at a
fixed sample interval, publishes a read-only snapshot under a lock, self-terminates when
the run finishes, and treats a tick failure as fail-open (log and keep going) so a
monitoring error can never stall or crash a test run.
"""

from threading import Event, Lock, Thread

from ..logger import get_logger
from .const import FAIL_OPEN_ERRORS

log = get_logger()


class MonitorThread(Thread):
    """Daemon thread that ticks at a fixed interval for the lifetime of a run.

    Subclasses implement :meth:`tick` (one evaluation + snapshot publish) and may
    override :meth:`on_tick_error` to reset their published snapshot after a failed
    tick. ``_state_lock`` is provided for the publish/read pair.
    """

    def __init__(self, is_running_fn, sample_interval: float) -> None:
        """
        :param is_running_fn: Callable returning ``True`` while the run is in progress;
            the loop exits (self-terminates) once it returns ``False``.
        :param sample_interval: Seconds between ticks (floored at 0.1).
        """
        super().__init__(daemon=True)
        self._is_running_fn = is_running_fn
        self._sample_interval = max(sample_interval, 0.1)
        self._stop_event = Event()
        self._state_lock = Lock()

    def stop(self) -> None:
        """Signal the monitor loop to exit after the current tick."""
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except FAIL_OPEN_ERRORS as e:  # fail-open: a monitor error must never stall or crash the run
                log.warning(f"{type(self).__name__} tick error (logged once per tick): {e}")
                self.on_tick_error(e)
            if not self._is_running_fn():
                break  # run finished — workers all drained
            self._stop_event.wait(self._sample_interval)

    def tick(self) -> None:
        """Evaluate the monitor's signal once and publish a fresh snapshot. Subclasses implement."""
        raise NotImplementedError

    def on_tick_error(self, error: BaseException) -> None:
        """Hook called after a failed tick; default is a no-op. Subclasses may reset their snapshot."""
