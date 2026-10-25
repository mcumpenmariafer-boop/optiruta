"""Pruebas contra PostgreSQL real: pytest --ds=config.settings_test_pg"""
from .settings_test import *  # noqa: F401,F403
from .settings import DATABASES as _PG

DATABASES = _PG
