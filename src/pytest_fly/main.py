from balsa import Balsa

from .__version__ import application_name, author
from .logger import get_logger
from .paths import get_default_data_dir
from .preferences import get_pref
from .gui import fly_main

log = get_logger(application_name)


class FlyLogger(Balsa):
    def __init__(self):
        pref = get_pref()
        super().__init__(name=application_name, author=author, verbose=pref.verbose, gui=False)


def app_main():

    fly_logger = FlyLogger()
    fly_logger.init_logger()

    data_dir = get_default_data_dir()

    fly_main(data_dir)
