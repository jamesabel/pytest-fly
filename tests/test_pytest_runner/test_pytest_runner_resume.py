"""Test RESUME mode: after all tests pass, a Resume run should not re-run any tests."""

from dataclasses import replace

from pytest_fly.db import PytestProcessInfoDB
from pytest_fly.guid import generate_uuid
from pytest_fly.interfaces import PyTestFlyExitCode, PytestRunnerState, ScheduledTest
from pytest_fly.pytest_runner import PytestRunner
from pytest_fly.pytest_runner.pytest_runner import PytestRunState
from pytest_fly.pytest_runner.test_list import GetTests

from ..paths import get_temp_dir


def _filter_for_resume(tests: list[ScheduledTest], prior_results: list) -> list[ScheduledTest]:
    """Replicate ControlWindow._filter_for_resume for RESUME mode."""
    passed = {r.name for r in prior_results if r.exit_code == PyTestFlyExitCode.OK}
    return [t for t in tests if t.node_id not in passed]


def _copy_prior_records(run_guid, prior_results, skipped_node_ids, data_dir):
    """Replicate the RESUME record-copying logic from ControlWindow.run."""
    prior_by_name = {}
    for r in prior_results:
        prior_by_name.setdefault(r.name, []).append(r)
    with PytestProcessInfoDB(data_dir) as db:
        for node_id in sorted(skipped_node_ids):
            for record in prior_by_name.get(node_id, []):
                db.write(replace(record, run_guid=run_guid))


def test_resume_after_all_pass(app):
    """When all tests pass in the first run, a RESUME run should queue zero tests."""

    data_dir = get_temp_dir("test_resume_after_all_pass")

    with PytestProcessInfoDB(data_dir) as db:
        db.delete()

    test_node_ids = ["tests/test_no_operation.py", "tests/test_3_sec_operation.py"]
    scheduled_tests = [ScheduledTest(node_id=nid, singleton=False, duration=None, coverage=None) for nid in test_node_ids]

    # --- Run 1: RESTART (all tests should pass) ---
    run_guid_1 = generate_uuid()
    runner_1 = PytestRunner(run_guid_1, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=3.0)
    runner_1.start()
    runner_1.join(60.0)
    assert not runner_1.is_running()

    with PytestProcessInfoDB(data_dir) as db:
        run_1_results = db.query(run_guid_1)

    # Verify both tests passed
    passed_names = {r.name for r in run_1_results if r.exit_code == PyTestFlyExitCode.OK}
    assert passed_names == set(test_node_ids), f"Expected all tests to pass, got {passed_names}"

    # --- Run 2: RESUME (no tests should be re-run) ---
    run_guid_2 = generate_uuid()

    # Query prior results the same way control_window.run() does
    with PytestProcessInfoDB(data_dir) as db:
        prior_results = db.query()  # most recent run (run_guid_1)

    # Filter — should remove all tests since all passed
    tests_to_run = _filter_for_resume(scheduled_tests, prior_results)
    assert tests_to_run == [], f"Expected no tests to re-run, but got {[t.node_id for t in tests_to_run]}"

    # Copy prior records for skipped tests (same as control_window.run)
    all_node_ids = {t.node_id for t in scheduled_tests}
    skipped_node_ids = all_node_ids - {t.node_id for t in tests_to_run}
    assert skipped_node_ids == set(test_node_ids)
    _copy_prior_records(run_guid_2, prior_results, skipped_node_ids, data_dir)

    # Start PytestRunner with empty test list
    runner_2 = PytestRunner(run_guid_2, tests_to_run, number_of_processes=2, data_dir=data_dir, update_rate=3.0)
    runner_2.start()
    joined = runner_2.join(10.0)
    assert joined, "RESUME runner should finish almost immediately with no tests"
    assert not runner_2.is_running()

    # Verify: the only records for run_guid_2 should be the copied ones (no fresh QUEUED records)
    with PytestProcessInfoDB(data_dir) as db:
        run_2_results = db.query(run_guid_2)

    fresh_queued = [r for r in run_2_results if r.exit_code == PyTestFlyExitCode.NONE]
    # Copied records include the original QUEUED/RUNNING records (exit_code=NONE),
    # but there should be no ADDITIONAL queued records from PytestRunner
    original_none_count = sum(1 for r in run_1_results if r.exit_code == PyTestFlyExitCode.NONE)
    assert len(fresh_queued) == original_none_count, (
        f"Expected only copied NONE records ({original_none_count}), but found {len(fresh_queued)} — PytestRunner may have queued tests that should have been skipped"
    )

    # --- Run 3: another RESUME should also have nothing to run ---
    generate_uuid()  # advance the GUID clock (not stored — we only need db.query() to return run_guid_2)
    with PytestProcessInfoDB(data_dir) as db:
        prior_results_3 = db.query()  # most recent run (run_guid_2)

    # The most recent run should be run_guid_2
    assert all(r.run_guid == run_guid_2 for r in prior_results_3), "db.query() should return the most recent run"

    tests_to_run_3 = _filter_for_resume(scheduled_tests, prior_results_3)
    assert tests_to_run_3 == [], f"Third RESUME should also have no tests, but got {[t.node_id for t in tests_to_run_3]}"


def test_resume_uses_discovered_test_names(app):
    """Verify GetTests node_ids match PytestRunner DB names so the RESUME filter works.

    This catches path-format mismatches (e.g. backslashes vs forward slashes on Windows).
    """

    data_dir = get_temp_dir("test_resume_discovered_names")

    with PytestProcessInfoDB(data_dir) as db:
        db.delete()

    # Discover tests the same way the GUI does
    get_tests = GetTests()
    get_tests.start()
    get_tests.join(30.0)
    discovered = get_tests.get_tests()

    # Pick two known tests from the discovered list
    target_names = {"tests/test_no_operation.py", "tests/test_3_sec_operation.py"}
    scheduled_tests = [t for t in discovered if t.node_id in target_names]
    assert len(scheduled_tests) == 2, f"Expected 2 tests from discovery, got {[t.node_id for t in scheduled_tests]}"

    # Run them
    run_guid = generate_uuid()
    runner = PytestRunner(run_guid, scheduled_tests, number_of_processes=2, data_dir=data_dir, update_rate=3.0)
    runner.start()
    runner.join(60.0)
    assert not runner.is_running()

    # Query results and verify names match discovered node_ids exactly
    with PytestProcessInfoDB(data_dir) as db:
        results = db.query(run_guid)

    db_names = {r.name for r in results}
    discovered_ids = {t.node_id for t in scheduled_tests}
    assert db_names == discovered_ids, f"DB names {db_names} don't match discovered IDs {discovered_ids}"

    # Now verify the RESUME filter works with these actual names
    with PytestProcessInfoDB(data_dir) as db:
        prior = db.query()

    tests_to_run = _filter_for_resume(scheduled_tests, prior)
    assert tests_to_run == [], f"RESUME filter should exclude all passed tests, but got {[t.node_id for t in tests_to_run]}"


def test_resume_copied_records_show_pass_state(app):
    """Verify that copied prior-run records result in PASS state, not QUEUED."""

    data_dir = get_temp_dir("test_resume_copied_state")

    with PytestProcessInfoDB(data_dir) as db:
        db.delete()

    test_node_ids = ["tests/test_no_operation.py"]
    scheduled_tests = [ScheduledTest(node_id=nid, singleton=False, duration=None, coverage=None) for nid in test_node_ids]

    # Run 1: test passes
    run_guid_1 = generate_uuid()
    runner = PytestRunner(run_guid_1, scheduled_tests, number_of_processes=1, data_dir=data_dir, update_rate=3.0)
    runner.start()
    runner.join(30.0)

    with PytestProcessInfoDB(data_dir) as db:
        prior_results = db.query(run_guid_1)

    # Run 2: RESUME — copy records
    run_guid_2 = generate_uuid()
    _copy_prior_records(run_guid_2, prior_results, set(test_node_ids), data_dir)

    # Query the copied records and check the run state
    with PytestProcessInfoDB(data_dir) as db:
        run_2_results = db.query(run_guid_2)

    from collections import defaultdict

    grouped = defaultdict(list)
    for r in run_2_results:
        grouped[r.name].append(r)

    for name, infos in grouped.items():
        state = PytestRunState(infos)
        assert state.get_state() == PytestRunnerState.PASS, f"Copied records for {name} should show PASS but got {state.get_state()}"
