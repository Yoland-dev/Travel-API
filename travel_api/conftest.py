"""Pytest configuration: use a fast password hasher so the suite runs quickly."""
import pytest


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
