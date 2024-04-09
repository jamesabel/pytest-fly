from pprint import pprint

from .db import get_most_recent_start_and_finish, get_most_recent_run_info

def visualize():
    test_name, start, finish = get_most_recent_start_and_finish()
    print(f"{test_name=}, {start=}, {finish=}")
    run_info = get_most_recent_run_info()
    pprint(run_info)