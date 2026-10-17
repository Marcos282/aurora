import os

os.environ["DJANGO_SECRET_KEY"] = "test-only"
from .settings import *  # noqa: E402,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PAYMENTS_ENABLED = False

# Legacy suite continues to exercise the archived Aurora routes.
ROOT_URLCONF = "config.urls"
MIDDLEWARE = [m for m in MIDDLEWARE if m != "hotspot.middleware.TenantMiddleware"] + ["core.middleware.AdultAccessMiddleware"]
LOGIN_URL = 'login'
