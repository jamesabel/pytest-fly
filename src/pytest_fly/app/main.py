from argparse import ArgumentParser
from pathlib import Path

from balsa import Balsa

from ..__version__ import application_name, author
from .logger import get_logger
from .model.preferences import get_pref
from .view import fly_main

log = get_logger(application_name)


def parse_args():
    parser = ArgumentParser(description="pytest-fly: a GUI for pytest")
    parser.add_argument("-d", "--db", type=str, help="override for DB file path (handy for testing)")
    args = parser.parse_args()
    return args


class FlyLogger(Balsa):
    def __init__(self):
        pref = get_pref()
        super().__init__(name=application_name, author=author, verbose=pref.verbose, gui=False)


def app_main():

    args = parse_args()

    fly_logger = FlyLogger()
    fly_logger.init_logger()

    if args.db is None:
        db_path = None
    else:
        db_path = Path(args.db).resolve()
        log.info(f"{db_path=}")
    fly_main(db_path)
