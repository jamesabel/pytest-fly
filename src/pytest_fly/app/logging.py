from logging import Logger

from balsa import Balsa, get_logger as balsa_get_logger

from ..__version__ import application_name, author
from .preferences import get_pref

def get_logger(name: str = application_name) -> Logger:
    return balsa_get_logger(name)

class FlyLogger(Balsa):
    def __init__(self):
        pref = get_pref()
        super().__init__(name=application_name, author=author, verbose = pref.verbose, gui=False)
