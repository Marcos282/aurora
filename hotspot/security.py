from contextlib import contextmanager
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction


class RouterUnavailable(Exception):
    pass


def cipher():
    try:
        return Fernet(settings.NOVAINFO_CREDENTIAL_KEY.encode())
    except (ValueError, TypeError):
        raise RouterUnavailable('Chave de criptografia não configurada.') from None


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise RouterUnavailable('Credencial indisponível.') from None


def validate_login_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path != '/login':
        raise ValidationError('Informe uma URL HTTPS terminada em /login, sem parâmetros ou credenciais.')
    return value


@contextmanager
def tenant_scope(tenant_id):
    # SET LOCAL cannot leak a tenant into a reused database connection.
    with transaction.atomic():
        previous = ''
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('novainfo.tenant_id', true)")
                previous = cursor.fetchone()[0] or ''
                cursor.execute("SELECT set_config('novainfo.tenant_id', %s, true)", [str(tenant_id)])
        try:
            yield
        finally:
            if connection.vendor == 'postgresql' and not connection.needs_rollback:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('novainfo.tenant_id', %s, true)", [previous])
