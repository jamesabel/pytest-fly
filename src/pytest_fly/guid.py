"""UUIDv7 generation and decoding utilities for time-ordered run identifiers."""

import uuid
from datetime import datetime, timezone

from typeguard import typechecked
from uuid6 import uuid7


@typechecked()
def generate_uuid() -> str:
    """
    Generate a UUIDv7 (time-ordered, timestamp-encoded).

    Time-ordering is load-bearing: run GUIDs sort lexicographically in creation order,
    which :meth:`pytest_fly.db.PytestProcessInfoDB.query` relies on to select the most
    recent run via ``MAX(run_guid)``.
    """
    u = str(uuid7())
    return u


@typechecked()
def decode_uuid_timestamp(uuid_string: str) -> datetime:
    """
    Extract the UTC timestamp encoded in a UUIDv7.

    UUIDv7 layout:
      - Top 48 bits = Unix epoch milliseconds
    """
    # UUID is a 128-bit integer
    u: uuid.UUID = uuid.UUID(uuid_string)
    uuid_int: int = u.int

    # Shift right to keep the top 48 bits
    timestamp_ms: int = uuid_int >> 80

    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
