from logging import Logger

from balsa import get_logger as balsa_get_logger

from ..__version__ import application_name


def get_logger(name: str = application_name) -> Logger:
    return balsa_get_logger(name)
