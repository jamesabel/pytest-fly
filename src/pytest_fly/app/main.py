from . import FlyLogger
from .view import fly_main

def app_main():
    fly_logger = FlyLogger()
    fly_logger.init_logger()
    fly_main()
