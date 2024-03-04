# File: pytest_fly/plugin.py

import pytest
import sqlite3
import threading
import time
import random
from datetime import datetime

db_path = "test_results.db"  # Default database path
lock = threading.Lock()  # Ensure thread safety

def setup_database():
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                test_name TEXT,
                start_time TEXT,
                end_time TEXT,
                status TEXT
            )
        ''')
        conn.commit()

def record_test_result(test_name: str, start_time: str, end_time: str, status: str):
    retries = 0
    max_retries = 10

    while retries < max_retries:
        try:
            with lock, sqlite3.connect(db_path, timeout=10.0) as conn:
                conn.execute("BEGIN TRANSACTION")
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO test_results (test_name, start_time, end_time, status)
                    VALUES (?, ?, ?, ?)
                ''', (test_name, start_time, end_time, status))
                conn.commit()
                break
        except sqlite3.OperationalError as e:
            print(f"Database access error: {e}. Retrying...")
            time.sleep(random.uniform(0.1, 0.5))
            retries += 1
    else:
        print("Failed to record test result after multiple retries.")

def pytest_addoption(parser):
    parser.addoption("--fly", action="store_true", help="Activate the pytest-fly plugin to record test results in a SQLite database.")
    parser.addoption("--db-path", action="store", help="Path to the SQLite database for recording test results.")

def pytest_configure(config):
    global db_path
    if config.getoption("fly"):
        db_path = config.getoption("db_path") or config.getini("db_path")
        setup_database()

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if not item.config.getoption("fly"):
        return

    start_time = datetime.now()
    reports = yield from pytest.hookimpl.call_matching_hooks(f"pytest_runtest_protocol", item=item, nextitem=nextitem, _ispytest=True)

    status = "passed"
    for report in reports:
        if report.failed:
            status = "failed"
            break
        elif report.skipped:
            status = "skipped"

    end_time = datetime.now()
    record_test_result(item.nodeid, start_time.isoformat(), end_time.isoformat(), status)

def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("fly"):
        print("Test results recorded to", db_path)
