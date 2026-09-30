"""Development settings: SQLite, verbose errors, console email."""
from .base import *  # noqa: F401,F403

DEBUG = config("DEBUG", default=True, cast=bool)  # noqa: F405
