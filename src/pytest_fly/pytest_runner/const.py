"""Constants for the pytest runner subsystem."""

import sqlite3

import psutil

TIMEOUT = 20.0  # seconds – upper bound for join() calls on test processes

# Exception types the fail-open recovery paths (monitor ticks, DB-backed completion
# reads, force-stop finalization) may plausibly raise at runtime — DB reads (sqlite3 via
# msqlite), psutil process probes, filesystem access, and value/lookup errors on partial
# data. Enumerated (rather than a blanket ``except Exception``) so genuine programming
# errors still surface in tests instead of being silently swallowed.
FAIL_OPEN_ERRORS = (OSError, RuntimeError, ValueError, KeyError, sqlite3.Error, psutil.Error)

# Byte-size units shared by the resource samplers (system monitor, resource guard).
BYTES_PER_MB = 1024.0 * 1024.0
BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0
