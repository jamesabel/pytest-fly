from datetime import datetime, timezone

from pytest_fly.guid import generate_uuid, decode_uuid_timestamp


def test_generate_uuid():
    uuid_value = generate_uuid()
    uuid_str = str(uuid_value)
    assert len(uuid_str) == 36  # standard UUID string length
    assert "-" in uuid_str  # should contain hyphens


def test_decode_uuid_timestamp():
    uuid_value = generate_uuid()
    timestamp = decode_uuid_timestamp(uuid_value)
    assert timestamp.tzinfo is not None  # should be timezone-aware
    # Check that the timestamp is reasonably close to now (within a minute)
    now = datetime.now(timezone.utc)
    assert abs((now - timestamp).total_seconds()) < 60
