from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from hotspot.models import AuditLog, Membership, Tenant
from hotspot.security import tenant_scope


class Command(BaseCommand):
    help = 'Cria um estabelecimento e vincula um usuário sem alterar contas existentes.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('name')
        parser.add_argument('username')
        parser.add_argument('--role', choices=['owner', 'operator', 'viewer'], default='owner')

    @transaction.atomic
    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(slug=options['slug']).first()
        if not tenant:
            tenant = Tenant(slug=options['slug'], name=options['name'])
            tenant.full_clean()
            tenant.save()
        User = get_user_model()
        user = User.objects.filter(username=options['username']).first()
        if not user:
            password = getpass('Senha do novo usuário: ')
            if password != getpass('Confirme a senha: '):
                raise CommandError('As senhas não conferem.')
            user = User(username=options['username'])
            try:
                validate_password(password, user=user)
            except ValidationError as exc:
                raise CommandError('; '.join(exc.messages)) from None
            user.set_password(password)
            user.full_clean()
            user.save()
        membership = Membership.objects.filter(user=user).first()
        if membership:
            if membership.tenant_id != tenant.pk:
                raise CommandError('Este usuário já pertence a outro estabelecimento; nenhum vínculo foi alterado.')
            self.stdout.write('Vínculo já existente; permissões preservadas.')
        else:
            Membership.objects.create(tenant=tenant, user=user, role=options['role'])
            with tenant_scope(tenant.pk):
                AuditLog.objects.create(tenant=tenant, action='membership_provisioned', object_id=str(user.pk))
        self.stdout.write(self.style.SUCCESS(f'Estabelecimento pronto: {tenant.slug}'))
