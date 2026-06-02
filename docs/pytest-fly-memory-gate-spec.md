# Spec: Memory-aware module admission control for pytest-fly

> Hand this document to Claude Code running in the **pytest-fly** repository. It is
> self-contained and assumes no knowledge of any particular project under test. The
> implementing agent should read the pytest-fly source to find the real controller
> structure and wire the gate into it; the names below are illustrative.

## Context for the implementing agent

pytest-fly runs test **modules** (Python modules or packages) in parallel by dispatching
them from a **central controller process** to a pool of workers. Each worker runs one
module at a time, and a module may spawn its own subprocess tree (the test code under it
can fan out heavily). The controller has the worker **PID** for each in-flight module and
receives a per-module **completion callback**.

The problem: under parallel execution, total memory demand is the sum across all module
subtrees, and on Windows the limit actually hit is the **system commit limit** (physical
RAM + pagefile), *not* free physical RAM. A box can show plenty of free RAM while commit
is the wall — the failure surfaces as "the paging file is too small for this operation to
complete" and as `BrokenProcessPool` / crashed workers. Counting processes does not prevent
this, because module memory cost varies by orders of magnitude and the controller can't see
grandchild processes.

**Goal:** add an admission gate in the controller that decides *whether to dispatch the
next module now* based on a live OS-level memory signal, so the suite throttles itself under
memory pressure instead of OOMing — while running at full width when there's headroom.
Windows-only is fine for v1, but isolate the OS-specific read behind one function so other
platforms can be added later.

First, **read the repo** to find: the controller's dispatch loop, how it tracks idle workers
and pending modules, the worker PID for an in-flight module, and the per-module completion
callback. Wire the gate into those.

## Key insight (do not lose this)

The gate reads a **machine-wide** number (system commit charge), not a process count. That
means it automatically accounts for memory used by grandchild processes the controller never
spawned — they show up in the global commit charge regardless. This is why the gate works
without the controller needing any knowledge of what a module spawns internally.

## The OS signal (Windows)

Read system commit via Win32 `GetPerformanceInfo` (psapi). `CommitLimit` and `CommitTotal`
are in pages; multiply by `PageSize`. Neither `psutil.virtual_memory()` (physical RAM) nor
`psutil.swap_memory()` (pagefile in use) exposes the commit limit, so the ctypes call is
required.

```python
import ctypes
from ctypes import wintypes

def commit_charge_and_limit() -> tuple[int, int]:
    """(CommitTotal, CommitLimit) in bytes via GetPerformanceInfo. Windows only."""
    class PERF(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("CommitTotal", ctypes.c_size_t),
                    ("CommitLimit", ctypes.c_size_t), ("CommitPeak", ctypes.c_size_t),
                    ("PhysicalTotal", ctypes.c_size_t), ("PhysicalAvailable", ctypes.c_size_t),
                    ("SystemCache", ctypes.c_size_t), ("KernelTotal", ctypes.c_size_t),
                    ("KernelPaged", ctypes.c_size_t), ("KernelNonpaged", ctypes.c_size_t),
                    ("PageSize", ctypes.c_size_t), ("HandleCount", wintypes.DWORD),
                    ("ProcessCount", wintypes.DWORD), ("ThreadCount", wintypes.DWORD)]
    info = PERF(); info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise OSError("GetPerformanceInfo failed")
    page = info.PageSize
    return info.CommitTotal * page, info.CommitLimit * page
```

Isolate this behind a small `headroom()`/`commit_charge_and_limit()` seam so Linux
(`/proc/meminfo` `MemAvailable` + swap) and macOS can be added later without touching the
gate logic.

## Admission algorithm

When the controller has a free worker and a queue of pending modules, decide per candidate
module:

```
charge, limit  = commit_charge_and_limit()
reserved       = sum over in-flight modules of  estimate(module) * reserve_fraction(elapsed)
effective_used = charge + reserved
headroom       = limit - effective_used
need           = estimate(candidate) + safety_margin
floor_ok       = (limit - charge) >= limit * floor_fraction

admit(candidate) if:
      no modules are currently in flight           # min-1 forward-progress guarantee
  OR  (headroom >= need AND floor_ok)
```

Two independent terms, each with a job:

1. **`charge` (measured)** — the real wall; catches everything including grandchildren and
   anything the per-module estimate underestimates.
2. **`reserved` (predicted)** — covers the gap between dispatching a module and that module's
   processes actually allocating their memory. Without it, the gate is blind to in-flight
   modules whose cost has not yet materialized in `charge`, and it will overshoot by admitting
   several before any of them ramps up.

**min-1 guarantee** is mandatory: if nothing is in flight, always admit, even if the module
doesn't "fit." Otherwise one oversized module deadlocks the whole suite. This degrades cleanly
to serial execution under extreme pressure.

**Scheduling, not just blocking:** because the unit is a module, prefer to scan the pending
queue and dispatch the first module that fits rather than head-of-line blocking on a heavy
one. If none fit but a worker is idle and nothing is in flight, dispatch the cheapest (min-1).
This lets light modules run while a heavy one waits for headroom.

## Reservation model: handle end-of-run peaks (important)

The shape of a module's memory-vs-time curve determines how the reservation must behave. Two
regimes:

- **Early ramp, then plateau** — cost materializes in `charge` within seconds. You can decay
  the reservation toward zero once measured `charge` has caught up, to avoid double-counting.
- **Peak at the end** — `charge` stays *low* for almost the entire module duration and only
  jumps at the very end (e.g. report generation). **This is the norn workload.**

For an end peak, decaying the reservation is actively harmful: during the long low-`charge`
period the gate would see "lots of headroom + a faded reservation," admit more modules, and
then several in-flight modules would all hit their end-spike **simultaneously** — which is
exactly the OOM scenario. So for end-peaking modules the reservation must be **held at full
estimate for the module's entire lifetime**. The brief "double-count" at the end (full
reservation *plus* the now-real measured `charge`) is not a bug — it correctly makes the gate
refuse new work precisely when in-flight modules are converging on their peaks.

Make the reservation decay a configurable mode, defaulting to **no decay**:

```
reserved(module) = estimate(module) * reserve_fraction(elapsed)

reserve_decay = "none"    (DEFAULT)  -> reserve_fraction = 1.0 for the whole lifetime
              = "linear"             -> reserve_fraction = max(min_reserve_fraction,
                                                              1 - elapsed / ramp_seconds)
```

- **Default `"none"`** — hold the full estimate until `on_complete`. Correct for end-peaking
  modules; conservative for unknown ones.
- **`"linear"`** — for suites whose modules ramp early and plateau. Uses `ramp_seconds` and a
  `min_reserve_fraction` floor. Not the default.

Use `time.monotonic()` for `elapsed`.

**Consequence:** with no decay, estimate accuracy carries more weight mid-run (the reservation
is the primary signal while measured `charge` is still low). Two things keep that safe — see
the next section.

## Per-module cost estimate (self-learning)

Module cost is **attributable** even under concurrency, because each worker runs one module at
a time. On Windows, `psutil.Process().memory_info().pagefile` is a process's commit
contribution ("Commit Size" in Task Manager). Sum it over the **worker process plus all
descendants** to get the module's commit footprint.

```python
import psutil

def subtree_commit(pid: int) -> int:
    try:
        proc = psutil.Process(pid)
        procs = [proc, *proc.children(recursive=True)]
    except psutil.NoSuchProcess:
        return 0
    total = 0
    for p in procs:
        try:
            total += p.memory_info().pagefile
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total
```

- Snapshot `subtree_commit(worker_pid)` in the **completion callback, before the worker tears
  down its subtree** (children still alive). Because cost peaks at the end, this moment
  naturally captures the peak — the learned estimate converges to the true peak quickly with no
  extra sampling.
- Store a short history (last ~5 runs) per module key (module path); use the **median** as the
  estimate. Persist to JSON or SQLite in pytest-fly's cache/config dir so estimates survive
  across runs.
- First-ever sighting of a module → use `default_module_cost`. Set this on the **generous**
  side: an unknown module should be assumed heavy until measured once, so a new module's first
  run doesn't over-admit and OOM before it's been learned.

## Component shape

- `commit_charge_and_limit() -> (int, int)` — the OS read above; the only Windows-specific
  piece, behind a small seam for future platforms.
- `CostStore` — `estimate(module) -> int`, `record(module, cost) -> None`; persisted, median
  over recent history, `default_module_cost` for unknown modules.
- `MemoryGate` — holds `CostStore` and `_inflight: dict[worker_pid, (module, dispatch_monotonic)]`.
  Methods:
  - `can_admit(module) -> bool` — the algorithm above.
  - `on_dispatch(worker_pid, module)` — record start time in `_inflight`.
  - `on_complete(worker_pid, module)` — `CostStore.record(module, subtree_commit(worker_pid))`,
    then drop from `_inflight`.
  - Not thread-safe by design — call only from the controller's dispatch loop/thread. If the
    controller is multi-threaded, guard `_inflight` with a lock.

## Config knobs (expose via pytest-fly's existing config mechanism)

- `safety_margin` (bytes, default ~2 GB) — slack above the estimate for spikes/error.
- `reserve_decay` (`"none"` default | `"linear"`) — see reservation model.
- `ramp_seconds` (default ~45) — decay window when `reserve_decay="linear"`.
- `min_reserve_fraction` (default ~0.5) — floor for linear decay.
- `floor_fraction` (default ~0.10) — hard backstop: never dispatch if absolute headroom drops
  below this fraction of the commit limit, regardless of estimates.
- `default_module_cost` (bytes) — estimate for unseen modules; set generously.
- An **enable/disable switch** (config flag and/or env var).

## Fail-open (non-negotiable)

The gate must never break or stall a test run. Wrap every OS/psutil call so any error (or the
disable switch) turns `can_admit` into "always True" and logs a single warning. A bad memory
reading must degrade to full parallelism, never to a hang or a crash.

## Tests

Inject `commit_charge_and_limit` and `subtree_commit` as dependencies so tests don't depend on
the host's real memory, and inject a fake monotonic clock.

- **MemoryGate (unit):**
  - Admits freely when headroom is large.
  - Blocks a heavy module when headroom is tight, then admits it after an in-flight module
    completes (charge / reservation drops).
  - min-1: admits even an over-limit module when `_inflight` is empty.
  - `reserve_decay="none"`: reservation stays at full estimate for the whole lifetime; a second
    heavy dispatch is blocked even while measured `charge` is still low (the end-peak case).
  - `reserve_decay="linear"`: reservation fades over `ramp_seconds` down to `min_reserve_fraction`.
  - `floor_fraction` backstop blocks even when the per-module estimate would fit.
  - Fail-open: a raising `commit_charge_and_limit` makes `can_admit` return True and logs once.
- **CostStore:** median over history, `default_module_cost` for unknown module, round-trips
  through persistence.
- **Integration (optional, mark slow):** dispatch several mock modules with assigned fake costs
  against a fake commit limit; assert the gate never lets `reserved + charge` exceed the limit
  except under the min-1 case.

## Acceptance

- Under a deliberately oversubscribed run that previously OOM'd, the suite completes without
  commit-limit failures, throttling instead.
- Under a small run with ample headroom, modules dispatch at full configured width (the gate
  adds no meaningful latency).
- Disabling the gate restores prior behavior exactly.
