"""Constants for the pytest runner subsystem."""

TIMEOUT = 20.0  # seconds – upper bound for join() calls on test processes

# Byte-size units shared by the resource samplers (system monitor, resource guard).
BYTES_PER_MB = 1024.0 * 1024.0
BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0
