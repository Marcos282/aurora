import ipaddress
from getpass import getpass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from hotspot.models import AuditLog, Router, Tenant
from hotspot.security import RouterUnavailable, encrypt, tenant_scope, validate_login_url


class Command(BaseCommand):
    help = 'Configura o roteador de um estabelecimento. A senha é solicitada sem eco.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--ip', required=True)
        parser.add_argument('--api-user', required=True)
        parser.add_argument('--login-url', required=True)
        parser.add_argument('--hotspot-server', required=True)
        parser.add_argument('--port', type=int, default=443)

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options['slug'], active=True)
            address = ipaddress.ip_address(options['ip'])
            networks = [ipaddress.ip_network(n) for n in settings.NOVAINFO_WIREGUARD_NETWORKS]
            if address.version != 4 or address.is_loopback or address.is_link_local or not address.is_private or not any(address in n for n in networks):
                raise CommandError('O IP precisa pertencer à rede WireGuard configurada.')
            validate_login_url(options['login_url'])
            password = getpass('Senha da API do MikroTik (não será exibida): ')
            if not password:
                raise CommandError('Informe uma senha não vazia.')
            encrypted = encrypt(password)
            with tenant_scope(tenant.pk):
                router = Router.objects.filter(tenant=tenant).first() or Router(tenant=tenant)
                router.tunnel_ip = str(address)
                router.api_user = options['api_user']
                router.encrypted_password = encrypted
                router.login_url = options['login_url']
                router.hotspot_server = options['hotspot_server']
                router.https_port = options['port']
                router.full_clean()
                router.save()
                AuditLog.objects.create(tenant=tenant, action='router_configured')
        except Tenant.DoesNotExist:
            raise CommandError('Estabelecimento não encontrado.') from None
        except (ValueError, ValidationError, RouterUnavailable) as exc:
            # Do not render model validation details: they may contain credentials.
            raise CommandError('Configuração inválida. Confira IP, URL HTTPS, porta e chave de criptografia.') from None
        self.stdout.write(self.style.SUCCESS('Roteador configurado. A conectividade será validada pelo túnel em cada operação.'))
