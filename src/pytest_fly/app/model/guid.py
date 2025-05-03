from uuid6 import uuid7


def get_guid() -> str:
    # get a unique id that is monotonically increasing over time
    return str(uuid7())
