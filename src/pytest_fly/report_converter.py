from typing import Sized, Any
import json
import time
import platform
import getpass
from functools import cache

from _pytest.reports import BaseReport


@cache
def get_username() -> str:
    """
    Get the username of the current user
    """
    return getpass.getuser()


@cache
def get_computer_name() -> str:
    """
    Get the computer name
    """
    return platform.node()


def _convert_report_to_dict(report: BaseReport) -> dict[str, Any]:
    """
    Convert a pytest Report to a dict, excluding zero-length iterables, None values, and other data that's not serializable. This isn't perfect but it seems to preserve
    the data we're interested in.
    :param report: Pytest Report
    :return: a dict representation of the report
    """
    report_dict = {}
    for attr in dir(report):
        # Exclude private attributes and methods, None, and zero-length lists
        if not attr.startswith("__") and (value := getattr(report, attr)) is not None:
            has_size = isinstance(value, Sized)
            if not has_size or has_size and len(value) > 0:
                # Check if the attribute is serializable
                try:
                    json.dumps(value)
                    report_dict[attr] = value
                except TypeError:
                    # a string representation starting with "<" generally isn't a useful serialization, so ignore it
                    if not (s := str(value)).startswith("<"):
                        report_dict[attr] = s
    return report_dict


def report_to_json(report: BaseReport) -> str:
    """
    Convert Pytest Report object to a JSON string (as much as possible)
    :param report: Pytest Report
    :return: JSON string representation of the report
    """
    d = _convert_report_to_dict(report)
    # remove fields that we don't need that can have formatting issues with SQLite JSON
    removes = ["sections", "capstdout", "capstderr", "caplog"]
    for remove in removes:
        if remove in d:
            del d[remove]
    d["fly_timestamp"] = time.time()  # pytest-fly's own timestamp
    d["username"] = get_username()
    d["computer_name"] = get_computer_name()
    s = json.dumps(d)
    return s
