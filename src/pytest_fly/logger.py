from logging import Logger

from balsa import get_logger as balsa_get_logger

from pytest_fly.__version__ import application_name


def get_logger(name: str = application_name) -> Logger:
    """
    Return the application logger.

    Wraps :func:`balsa.get_logger` so that every module in the project imports
    the logger from one place, making it easy to swap implementations later.

    :param name: Logger name (defaults to the application name).
    :return: A standard-library :class:`~logging.Logger` instance.
    """
    return balsa_get_logger(name)
