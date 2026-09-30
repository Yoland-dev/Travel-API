"""Production settings: SECRET_KEY is mandatory and DEBUG is forced off."""
from .base import *  # noqa: F401,F403

SECRET_KEY = config("SECRET_KEY")  # noqa: F405 - no default: fail loudly if missing
DEBUG = False
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
