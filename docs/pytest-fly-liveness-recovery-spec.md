# Spec: Orphan reaping, stall detection, process-count admission, and terminal-state completion for pytest-fly

> Hand this document to Claude Code running in the **pytest-fly** repository. It is
> self-contained and assumes no knowledge of any particular project under test. The
> implementing agent should read the pytest-fly source to confirm the real runner
> structure and wire these changes into it; the class/method names below are taken from
> the current source and are accurate as of this writing, but verify them.

## Context for the implementing agent

pytest-fly runs test **modules** in parallel. A top-level `PytestRunner` thread enqueues
all scheduled tests onto a shared queue and spins up a pool of `_TestRunner` worker
threads. Each worker pulls one test at a time and runs it in a dedicated `PytestProcess`
(a `multiprocessing.Process`). A `_SingletonCoordinator` gates execution: a *normal* test
may run alongside other normal tests, a *singleton* test must run exclusively
(`acquire_singleton` waits until the active-slot count `_active == 0`). Per-test state
(QUEUED / RUNNING / PASS / FAIL / TERMINATED / STOPPED) is written to SQLite via
`PytestProcessInfoDB`; the GUI renders the run from that table and decides whether the
**Run** button is enabled from `PytestRunner.is_running()` (= "any worker thread alive").

The worker's run loop is, in essence:

```python
self.process = PytestProcess(...)
self.process.start()
while self.process.is_alive():      # _TestRunner._run_single_test
    if stop_requested: terminate_and_break()
    self.process.join(self.update_rate)
```

while holding a `_SingletonCoordinator` slot for the duration.

### The failure this spec addresses

A test under pytest-fly can spawn its own subprocess tree (the code under test fans out via
`multiprocessing` / `subprocess`). Two distinct things go wrong:

1. **Leaked orphans on the happy path.** `terminate_process_tree(...)` is only called when a
   test is *stopped or force-stopped*. On a normal PASS/FAIL, `PytestProcess.run()` returns
   but the test's spawned descendants are never reaped. They survive as orphans and
   accumulate across the run.

2. **A wedged worker hangs the whole run, invisibly and unrecoverably.** If a test's nested
   process tree deadlocks (e.g. a `multiprocessing.Pool` that never drains), `pytest.main()`
   never returns, the `PytestProcess` never exits, so `process.is_alive()` is `True` forever.
   The worker spins in its poll loop **holding a coordinator slot**. Because
   `acquire_singleton` requires `_active == 0`, every remaining singleton test starves;
   eventually every worker is blocked. `is_running()` stays `True` indefinitely, so the GUI
   shows "running" forever and the Run button never re-enables. The only escape today is
   killing the pytest-fly process from the OS.

**Observed instance:** a 190-test run finished its last dispatchable test, yet 26 tests
(almost all `@pytest.mark.singleton`) sat permanently in QUEUED, ~39 orphaned worker
processes remained alive, and the GUI reported "running" 8 hours later. System memory was
*not* exhausted (96 GB free, 100 GB commit free) — the existing commit-charge memory gate
correctly did nothing, because this is a **liveness** failure, not a memory failure.

### Explicit non-goal: no per-test timeout

Do **not** add an automatic per-test wall-clock timeout. There is no defensible maximum
test duration for this workload — a legitimately long test is indistinguishable from a hung
one by elapsed time alone. Instead, this spec makes the system **leak-free, observable,
recoverable, and honest about completion** through four independent changes, none of which
caps how long any individual test may run.

## Key insight (do not lose this)

The wedge is a **liveness** problem, and recovery hinges on one mechanism: a wedged worker
thread cannot be killed (Python threads aren't forcibly terminable), but it **unblocks on its
own the moment its test's process tree is killed** — `process.is_alive()` flips to `False`,
the poll loop exits, the thread ends and releases its coordinator slot. A worker blocked in
`acquire_singleton` unblocks when the stop event is set (the wait is stop-predicate
interruptible). So the entire recovery story reduces to: **kill the in-flight process trees +
set stop**, and every thread drains naturally. Every part below leans on this.

The four parts are independent and can land separately:

- **Part A — Reap the subtree after *every* test.** Stops orphan accumulation (problem 1).
- **Part B — Stall detection + manual recovery.** Makes the wedge visible and one-click
  recoverable, with no per-test clock (problem 2, detection/recovery).
- **Part C — Process-count admission gate.** Throttles runaway spawning before it hurts;
  complements the existing commit-charge gate.
- **Part D — Terminal-state run completion.** A wedged worker can no longer masquerade as a
  live run; the run reports honestly and the Run button can always recover.

---

## Part A — Reap the process subtree after every test (success or failure)

**Goal:** when a test process exits, guarantee none of its descendants survive — regardless
of how the test ended.

**Where:** `_TestRunner._run_single_test`. Today the descendant tree is only reaped via
`_terminate_process` on the stop path. Add reaping to the **normal-exit** path too.

**The catch — capture the tree *before* the parent dies.** Once `PytestProcess` exits you
can no longer enumerate its children from the parent (`psutil.Process(pid).children()` needs
the parent alive; on Windows there is no reparent-to-init you can walk). So you must snapshot
the descendant set *while the test is still running* and reap from that snapshot afterward:

1. During the poll loop (`while self.process.is_alive()`), on each iteration refresh a rolling
   snapshot of the descendant set as `{(pid, create_time)}` via
   `psutil.Process(self.process.pid).children(recursive=True)`. Store `create_time` to guard
   against PID reuse.
   - Alternatively, reuse the `ProcessMonitor` subtree walk that already exists for
     `subtree_commit` — have it publish the live descendant PID set so the worker doesn't walk
     the tree twice. Either is fine; pick whichever keeps the sampling in one place.
2. After the loop exits **and the process is confirmed not alive** (terminal completion — not
   the stop branch, which already tree-kills), in a `finally`, kill any snapshot entry still
   alive whose `create_time` matches. Reuse `terminate_process_tree` semantics or a small
   `reap_pids(snapshot)` helper that SIGTERMs then SIGKILLs survivors.

**Important guards:**

- Only reap on **terminal** exit. If the process is still alive (the wedge case), do *not*
  reap here — that path is Part B's manual force-stop. The normal-completion branch is reached
  only after `is_alive()` has gone `False`, so the parent is already dead and every snapshot
  survivor is by definition an orphan; killing it is unambiguous and is **not** a timeout
  decision.
- Match on `(pid, create_time)` before killing, so a recycled PID belonging to an unrelated
  process is never touched.
- Fail-open: any psutil error during reaping logs once and is swallowed; reaping must never
  raise into the worker loop.

**Why this is safe without a timeout:** it acts only *after* a test has already finished on
its own. It changes nothing about how long a test may run; it only ensures a finished test
leaves nothing behind.

---

## Part B — Stall detection and manual recovery (no automatic kill by default)

**Goal:** turn today's invisible, unrecoverable infinite hang into a **visible** condition the
user can clear in one click — without ever imposing a maximum test duration.

### The signal

Track two facts the runner already has access to:

1. **Run progress** — the timestamp of the last DB state transition (any test starting, or any
   test reaching a terminal state). Available from `PytestProcessInfoDB`.
2. **In-flight CPU activity** — the `ProcessMonitor` already samples each in-flight test's
   subtree CPU (`subtree` CPU percent). A deadlocked `multiprocessing` pool sits at ~0% CPU; a
   genuinely working test does not.

Declare the run **stalled** when **all** of the following hold for at least
`stall_warn_seconds`:

- there is ≥1 worker thread alive **and** ≥1 test still non-terminal (QUEUED or RUNNING);
- **no** DB state transition has occurred (nothing started, nothing finished); and
- **no** in-flight test's subtree CPU has exceeded `cpu_active_epsilon` (e.g. ~1%).

This is a **run-wide, activity-based** signal, deliberately *not* a per-test clock: a long
test that is actually doing work keeps tripping the CPU-activity condition and never flags,
no matter how long it runs. Only a run where *nothing is progressing and nothing is burning
CPU* flags.

**Acknowledged false-positive:** a test legitimately blocked on a slow network/IO wait also
shows ~0% CPU. That is *exactly* why the default behavior is advisory-only — see below.

### Behavior on stall (default: advisory + manual)

- **Log** a warning naming the stuck tests, which in-flight test(s) appear idle, and the
  current descendant-process count.
- **Surface a GUI banner / run state**, e.g. *"Run appears stalled — N tests not progressing,
  M worker processes idle."* Render it distinctly from a healthy "running" state.
- **Enable a "Force-stop & reset" action** that calls the existing stop path (sets the stop
  event → workers' poll loops tree-kill their in-flight processes → `acquire_singleton` waits
  abort → all threads drain), then drains the queue marking remaining tests STOPPED. This
  returns the GUI to an idle, runnable state **without** killing the pytest-fly process from
  the OS. Combine with Part D so the run is reported as finished afterward.

### Optional automatic escalation (default OFF)

Expose `auto_force_stop_on_stall` (default **False**). When explicitly enabled, after a
*longer* `stall_kill_seconds` (must be `> stall_warn_seconds`) the watchdog auto-invokes the
same Force-stop & reset. Off by default honors the "no automatic timeout" requirement; teams
who want unattended CI recovery can opt in, accepting the network-wait false-positive risk.

### Where

A single watchdog thread owned by `PytestRunner` (or folded into the existing
`system_monitor`). It only **reads** DB state and monitor samples and **emits** a signal/flag
the GUI consumes; it performs no termination itself except the opt-in escalation above. Keep
it read-only so it can never itself become a source of deadlock.

---

## Part C — Process-count admission gate (complement to the commit-charge gate)

**Goal:** throttle runaway process spawning before it exhausts handles/commit, catching the
spawn-explosion class of failure that the memory gate misses.

**Why it's needed:** the existing commit-charge gate reads a memory number; in the observed
incident memory was fine and the gate correctly stayed out of the way, yet the box still
accumulated dozens of stray processes. A process-count ceiling is the orthogonal signal.

**Signal:** mirror the memory gate's "machine-wide number" approach — count the **whole
descendant process tree under pytest-fly's controller PID** (this captures grandchildren the
controller never spawned). A `subtree_process_count(pid)` helper sits naturally next to the
existing `subtree_commit(pid)`:

```python
def subtree_process_count(pid: int) -> int:
    try:
        proc = psutil.Process(pid)
        return 1 + len(proc.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return 0
```

**Algorithm:** before dispatching the next test, defer (do not start a new test) while
`subtree_process_count(controller_pid) >= max_descendant_processes`. Preserve the
memory gate's **min-1 forward-progress guarantee**: if nothing is in flight, always admit, so
one heavy test can never deadlock the suite. Compose with the memory gate as a logical AND —
a test is admitted only if *both* gates pass (and the min-1 guarantee overrides both).

**Note:** this is admission control (prevents the situation from worsening), not recovery.
Parts A/B/D handle leaks and wedges; Part C reduces how often you reach them.

---

## Part D — Terminal-state run completion (stop a wedged worker from masquerading as "running")

**Goal:** completion and Run-button enablement should reflect **whether every test reached a
terminal state**, not merely whether a thread is still alive.

**Problem:** `is_running()` == "any `_TestRunner` thread alive." A wedged worker keeps it
`True` forever, so the run never reports done and Run never re-enables.

**Changes:**

1. Add a DB-derived completion view, e.g. `PytestRunner.get_run_completion()` returning
   `(n_terminal, n_total, stuck: list[str])`, where *terminal* means the test's latest record
   is OK / TESTS_FAILED / TERMINATED / STOPPED (i.e. **not** a latest record of `NONE`).
2. Drive the GUI's "run finished" indication and the **Run-button enablement** from this view
   (all tests terminal **or** the user force-stopped), rather than purely from thread
   liveness. A stuck worker thread can then never permanently disable Run.
3. When the queue is drained but some tests remain non-terminal because they can't be
   dispatched (e.g. singletons blocked behind a wedged slot), report the run as **"finished —
   N stuck/skipped"** and list them, instead of hanging. On Force-stop & reset (Part B), write
   those remaining tests as STOPPED so the table is internally consistent.

**Why recovery actually completes the threads:** as noted in the Key Insight — once Force-stop
tree-kills the in-flight processes, each wedged poll loop sees `is_alive() == False` and the
thread exits; each `acquire_singleton` waiter sees the stop predicate and returns. So after a
reset, `is_running()` legitimately goes `False` and the next run starts clean. Keep
`is_running()` for internal use, but gate the *user-facing* "can I start a new run?" decision
on terminal-state + reset.

---

## Config knobs (expose via pytest-fly's existing config mechanism)

- `stall_warn_seconds` (default ~600) — run-wide no-progress + no-CPU window before the stall
  banner appears.
- `cpu_active_epsilon` (default ~1.0 percent) — subtree CPU below this counts as "idle."
- `auto_force_stop_on_stall` (default **False**) — opt-in automatic escalation.
- `stall_kill_seconds` (default ~1800; must be `> stall_warn_seconds`) — escalation delay when
  the above is enabled.
- `max_descendant_processes` (default generous, e.g. `~8 × cpu_count` or a flat large value) —
  Part C ceiling.
- Enable/disable switches for the stall watchdog and the process-count gate (config flag
  and/or env var), independent of each other and of the commit-charge gate.

## Fail-open (non-negotiable)

None of these may break or stall a run. Wrap every OS/psutil/DB read so any error degrades to
the safe default and logs once:

- Part A reaping error → log once, leave orphans (no worse than today), never raise into the
  worker loop.
- Part B watchdog error or unavailable signal → no banner, no escalation (never a spurious
  auto-stop).
- Part C gate read failure or disable switch → `can_admit` returns `True` (full parallelism).
- Part D completion-view error → fall back to `is_running()`.

A bad reading must always degrade toward "let the run proceed," never toward a hang, crash, or
spurious kill.

## Tests

Inject the OS/psutil seams (`subtree_process_count`, the CPU-sample source, the DB
state-transition timestamp) and a fake monotonic clock so tests don't depend on the host.

- **Part A (subtree reaping):**
  - After a simulated test exits leaving live "descendant" PIDs in the snapshot, those PIDs are
    killed; on a clean test with no descendants, nothing is killed.
  - PID-reuse guard: a snapshot entry whose `create_time` no longer matches the live PID is
    **not** killed.
  - A raising psutil call logs once and does not propagate.
- **Part B (stall watchdog):**
  - No transitions + all-idle CPU for `> stall_warn_seconds` with non-terminal tests and a live
    worker → stall flag set; banner signal emitted.
  - In-flight CPU above `cpu_active_epsilon` → never flags, regardless of elapsed time (the
    "long but working" case).
  - A DB transition resets the timer.
  - `auto_force_stop_on_stall=False` → never auto-invokes stop; `=True` → invokes exactly once
    after `stall_kill_seconds`.
- **Part C (process-count gate):**
  - Blocks dispatch when subtree count ≥ ceiling; admits after it drops.
  - min-1: admits even over-ceiling when nothing is in flight.
  - Composes with the memory gate (AND); either gate blocking blocks dispatch.
  - Fail-open on read error.
- **Part D (terminal-state completion):**
  - `get_run_completion` counts a latest-`NONE` test as non-terminal and OK/FAIL/TERMINATED/
    STOPPED as terminal.
  - Queue drained with a singleton left blocked → run reported "finished — 1 stuck," that test
    listed.
  - After Force-stop & reset, all tests terminal and the "can start new run" gate is True even
    if a thread was briefly still unwinding.

## Acceptance

- A run containing a deliberately hung test (nested pool that never drains) **surfaces a stall
  banner** within `stall_warn_seconds` and is fully recovered by one Force-stop & reset — the
  Run button re-enables, no orphaned processes remain, and a fresh run starts clean. No
  pytest-fly process needs to be killed from the OS.
- A run containing a legitimately long-but-active test is **never** flagged or interrupted, no
  matter how long it runs (verifies the no-timeout requirement).
- After any normal run, the descendant-process count returns to baseline (Part A leaves no
  orphans).
- Under a run that spawns excessively, dispatch throttles at `max_descendant_processes` and
  proceeds once the count drops; disabling the gate restores prior behavior exactly.
