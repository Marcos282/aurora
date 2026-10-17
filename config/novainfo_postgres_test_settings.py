"""Only for the isolated PostgreSQL cluster described in NOVAINFO.md."""
import os
from .novainfo_test_settings import *  # noqa: F403

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'postgres',
    'USER': 'novainfo_test_admin',
    'HOST': os.environ.get('NOVAINFO_TEST_PG_SOCKET', '/tmp/novainfo-pg-socket'),
    'PORT': '55439',
    'TEST': {'NAME': 'test_novainfo'},
}}
