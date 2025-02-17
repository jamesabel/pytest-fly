from . import FlyLogger
from .view import view_main

def app_main():
    fly_logger = FlyLogger()
    fly_logger.init_logger()
    view_main()
