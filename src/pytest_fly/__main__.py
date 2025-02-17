from ismain import is_main

from .app import app_main

if is_main():
    app_main()
