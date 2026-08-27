"""psutil handle reuse: repeated subtree sampling must not reconstruct psutil.Process handles.

Constructing a ``psutil.Process`` runs a native init (a ``create_time`` identity read).  A native
access-violation crash during garbage collection (Windows, Python 3.14) was observed with exactly
those construction frames on the stack, so the samplers construct a handle once at first sight of
a pid and reuse it: ``subtree_members``/``subtree_pids``/``subtree_process_count`` walk a pid→ppid
snapshot with zero constructions (one native ``create_time`` read per member — psutil's in-time guard
against recycled pids, which doubles as each member's identity), and ``SubtreeCpuSampler`` and
``subtree_commit`` (with a ``ProcessHandleCache``) construct per process identity at most once across
samples.  psutil's per-read methods (``cpu_percent``, ``memory_info``) never detect pid reuse, so the
caches must: a cached handle is served only while the pid's creation time still matches.

All tests, fixtures, helpers, and constants in this module are AI-authored (Claude Code); the
per-test ownership markers below apply to the private helpers and constants as well.
"""

import os
import subprocess
import sys
import time
from collections import Counter

import psutil
import pytest

from pytest_fly.pytest_runner import commit_memory, process_monitor
from pytest_fly.pytest_runner.commit_memory import ProcessHandleCache, subtree_commit, subtree_members, subtree_pids, subtree_process_count
from pytest_fly.pytest_runner.process_monitor import SubtreeCpuSampler

# Root spawns one grandchild-of-the-test and waits on it, giving a stable 2-process tree
# (root + descendant) that spawns nothing new while a test samples it repeatedly.  The root
# *waits* (reaps) rather than sleeping alongside: on POSIX an unreaped killed child lingers as
# a zombie that is still the root's child in the pid->ppid map (psutil's children() keeps
# zombies too), which would keep a "departed" descendant in the tree indefinitely.
_TREE_SRC = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']).wait(); time.sleep(120)"

_TREE_SIZE = 2  # the spawned root plus its one child
_SPAWN_TIMEOUT = 15.0


def _kill_tree(root: subprocess.Popen) -> None:
    """Tear down the spawned tree: descendants first, then the root."""
    try:
        for child in psutil.Process(root.pid).children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    root.kill()
    root.wait(timeout=10)


def _wait_for_tree(root_pid: int) -> None:
    """Block until the root's child exists (the tree is fully spawned)."""
    deadline = time.time() + _SPAWN_TIMEOUT
    while len(subtree_pids(root_pid)) < _TREE_SIZE:
        assert time.time() < deadline, f"spawned tree did not reach {_TREE_SIZE} processes in {_SPAWN_TIMEOUT}s"
        time.sleep(0.1)


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
@pytest.fixture
def process_tree():
    """Spawn the 2-process tree and yield the root pid; tear the tree down afterwards."""
    root = subprocess.Popen([sys.executable, "-c", _TREE_SRC])
    try:
        _wait_for_tree(root.pid)
        yield root.pid
    finally:
        _kill_tree(root)


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
@pytest.fixture
def counting_process_class(monkeypatch):
    """Replace ``psutil.Process`` with a subclass that records every construction's pid."""
    constructions: list[int | None] = []
    real_process = psutil.Process

    class CountingProcess(real_process):
        def __init__(self, pid=None):
            constructions.append(pid)
            super().__init__(pid)

    monkeypatch.setattr(psutil, "Process", CountingProcess)
    return constructions


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_pids_matches_children_walk(process_tree):
    """subtree_pids reports the same membership as psutil's children(recursive=True) walk."""
    root_pid = process_tree
    via_children = {root_pid} | {p.pid for p in psutil.Process(root_pid).children(recursive=True)}
    members = subtree_pids(root_pid)
    assert members[0] == root_pid, "the root pid must be first"
    assert set(members) == via_children


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_pids_missing_pid_fails_open():
    """A pid that cannot exist yields an empty membership and a zero count, never an exception."""
    assert subtree_pids(-1) == []
    assert subtree_process_count(-1) == 0


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_process_count_constructs_no_handles(process_tree, counting_process_class):
    """Counting the tree is membership-only: zero psutil.Process constructions."""
    root_pid = process_tree
    assert subtree_process_count(root_pid) >= _TREE_SIZE
    assert counting_process_class == [], f"subtree_process_count constructed handles for pids {counting_process_class}"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_sampler_constructs_each_pid_once(process_tree, counting_process_class):
    """Across repeated samples of a stable tree, each pid's handle is constructed at most once."""
    root_pid = process_tree
    sampler = SubtreeCpuSampler()
    assert sampler.sample(root_pid) is None  # first sight primes root + descendants
    time.sleep(0.2)
    assert sampler.sample(root_pid) is not None  # primed tree yields a real reading
    time.sleep(0.2)
    assert sampler.sample(root_pid) is not None
    per_pid = Counter(counting_process_class)
    assert per_pid and max(per_pid.values()) == 1, f"handles reconstructed across samples: {[p for p, n in per_pid.items() if n > 1]}"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_sampler_drops_departed_handles(process_tree):
    """A descendant that exits is dropped from the sampler's handle cache on the next sample."""
    root_pid = process_tree
    sampler = SubtreeCpuSampler()
    sampler.sample(root_pid)  # prime: caches root + descendant handles
    descendant_pids = [member_pid for member_pid in subtree_pids(root_pid) if member_pid != root_pid]
    assert descendant_pids, "expected at least one descendant"
    for descendant_pid in descendant_pids:
        assert descendant_pid in sampler._handles._procs
        psutil.Process(descendant_pid).kill()
    deadline = time.time() + _SPAWN_TIMEOUT
    while any(pid in sampler._handles._procs for pid in descendant_pids):
        assert time.time() < deadline, "departed descendant handles were not dropped"
        time.sleep(0.1)
        sampler.sample(root_pid)


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_commit_with_cache_constructs_each_pid_once(process_tree, counting_process_class):
    """With a persistent ProcessHandleCache, repeated commit reads construct each handle at most once."""
    root_pid = process_tree
    handle_cache = ProcessHandleCache()
    assert subtree_commit(root_pid, handle_cache) > 0
    assert subtree_commit(root_pid, handle_cache) > 0
    per_pid = Counter(counting_process_class)
    assert per_pid and max(per_pid.values()) == 1, f"handles reconstructed across commit reads: {[p for p, n in per_pid.items() if n > 1]}"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_handle_cache_reconstructs_on_identity_change(counting_process_class):
    """A cached handle is served only for the identity (pid + create_time) it was built for.

    psutil's ``cpu_percent``/``memory_info`` do not detect pid reuse, so when the observed creation
    time of a pid changes the cache must drop the stale handle and construct one for the new process.
    """
    pid = os.getpid()
    ctime = subtree_members(pid)[pid]
    handle_cache = ProcessHandleCache()
    first = handle_cache.get(pid, ctime)
    assert first is not None and handle_cache.get(pid, ctime) is first, "same identity must reuse the handle"
    assert counting_process_class == [pid]
    assert handle_cache.holds(pid, ctime) and not handle_cache.holds(pid, ctime + 1.0)
    recycled = handle_cache.get(pid, ctime + 1.0)  # same pid, different creation time: a recycled pid
    assert recycled is not None and recycled is not first, "a recycled pid must get a fresh handle"
    assert counting_process_class == [pid, pid]
    assert not handle_cache.holds(pid, ctime), "the stale identity must be gone"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_sampler_reprimes_recycled_root_pid(monkeypatch, counting_process_class):
    """A sampled root whose pid now belongs to a *different* process is re-primed (``None``), not read.

    Regression: the stall watchdog's run-lifetime sampler keeps a finished worker's handle; when the OS
    hands that pid to a new worker, reading through the old handle yields a bogus cross-process delta
    that made the new worker look idle from its first tick.
    """
    pid = os.getpid()
    sampler = SubtreeCpuSampler()
    assert sampler.sample(pid) is None  # first sight primes
    time.sleep(0.2)
    assert sampler.sample(pid) is not None
    real_members = subtree_members(pid)
    monkeypatch.setattr(process_monitor, "subtree_members", lambda root_pid: {pid: real_members[pid] + 1.0})  # pid recycled by a new process
    assert sampler.sample(pid) is None, "a recycled root pid must re-prime, never yield a reading"
    assert counting_process_class.count(pid) == 2, "the recycled pid must get a fresh handle"
    time.sleep(0.2)
    assert sampler.sample(pid) is not None, "the fresh handle reads normally from its second sample on"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_sampler_unknown_when_root_vanishes_mid_run(monkeypatch):
    """A primed root whose membership can no longer be read yields ``None`` (unknown), never a partial total."""
    pid = os.getpid()
    sampler = SubtreeCpuSampler()
    sampler.sample(pid)
    monkeypatch.setattr(process_monitor, "subtree_members", lambda root_pid: {})  # root exited / tree unreadable
    assert sampler.sample(pid) is None
    assert pid not in sampler._handles._procs, "the vanished root's handle must be dropped"


# AI-GENERATED TEST (Claude Code) - delete this line to make this test human-owned.
def test_subtree_members_excludes_recycled_pid_orphans(monkeypatch):
    """The walk keeps psutil's ``children()`` guards: a "child" older than the root is a recycled-pid
    orphan (excluded, along with everything under it), and a pid gone since the snapshot is skipped."""
    pid = os.getpid()
    own_ctime = subtree_members(pid)[pid]
    # A real, live process *strictly* older than this one.  Not simply the parent: on Linux
    # /proc creation times have clock-tick resolution, so a parent that spawned this process
    # immediately can share its timestamp — and equal is in-time (psutil's rule too).
    older_pids = [
        candidate for candidate in sorted(psutil.pids()) if candidate != pid and (candidate_ctime := commit_memory._create_time(candidate)) is not None and candidate_ctime < own_ctime
    ]
    if not older_pids:
        pytest.skip("no readable process strictly older than this one")
    orphan_pid = older_pids[0]
    gone_pid = max(psutil.pids()) + 100_000  # no such process
    fake_snapshot = {pid: 1, orphan_pid: pid, gone_pid: pid, pid + 1_000_000: orphan_pid}
    monkeypatch.setattr(commit_memory, "_ppid_snapshot", lambda: fake_snapshot)
    members = subtree_members(pid)
    assert list(members) == [pid], f"expected only the root, got {members}"
    assert members[pid] == psutil.Process(pid).create_time()
    assert subtree_process_count(pid) == 1
