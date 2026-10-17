from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string
from django.urls import reverse

from hotspot.models import Tenant


class Command(BaseCommand):
    help = 'Gera o login.html de redirecionamento do MikroTik para a página externa Django.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--origin', required=True, help='Origem HTTPS pública do Nova Info, sem caminho.')

    def handle(self, *args, **options):
        origin = options['origin'].rstrip('/')
        parts = urlsplit(origin)
        if parts.scheme != 'https' or not parts.hostname or parts.path or parts.username or parts.password or parts.query or parts.fragment:
            raise CommandError('Informe uma origem HTTPS pública sem caminho ou credenciais.')
        try:
            tenant = Tenant.objects.get(slug=options['slug'], active=True)
        except Tenant.DoesNotExist:
            raise CommandError('Estabelecimento não encontrado.') from None
        url = origin + reverse('novainfo:captive', args=[tenant.pk])
        self.stdout.write(render_to_string('tenant/router_login.html', {'portal_url': url}))
