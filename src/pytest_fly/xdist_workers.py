import os


def _get_xdist_worker() -> str | None:
    x_dist_worker = os.environ.get("PYTEST_XDIST_WORKER")  # None if not running with xdist
    return x_dist_worker


def is_main_worker() -> bool:
    """
    Determines if this is the "main" worker, so that this is True only once per session.

    Returns:
        bool: True if this is the main worker, False otherwise.
    """
    x_dist_worker = _get_xdist_worker()
    return x_dist_worker is None or x_dist_worker.lower() == "gw0"
