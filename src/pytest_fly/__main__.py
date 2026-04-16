"""Entry point for ``python -m pytest_fly``."""

from ismain import is_main

from .main import app_main

if is_main():
    app_main()
