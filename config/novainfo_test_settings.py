from .test_settings import *  # noqa: F403

ROOT_URLCONF = 'config.novainfo_urls'
NOVAINFO_CREDENTIAL_KEY = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
NOVAINFO_WIREGUARD_NETWORKS = ['10.66.0.0/24']
NOVAINFO_WIREGUARD_INTERFACE = 'wg0'
NOVAINFO_BASE_DOMAIN = ''
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1', '.example.test']

MIDDLEWARE = [m for m in MIDDLEWARE if m != "core.middleware.AdultAccessMiddleware"] + ["hotspot.middleware.TenantMiddleware"]
LOGIN_URL = 'novainfo:login'
