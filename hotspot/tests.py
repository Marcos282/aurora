import json
import tempfile
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import BrandingForm
from .models import AccessGrant, AuditLog, Branding, Membership, Router, Tenant
from .router import RouterClient, verify_tunnel
from .security import RouterUnavailable, decrypt, encrypt, tenant_scope
from .services import issue_access


def picture(name='wallpaper.png'):
    output = BytesIO()
    Image.new('RGB', (100, 60), 'blue').save(output, 'PNG')
    return SimpleUploadedFile(name, output.getvalue(), content_type='image/png')


class TenantTests(TestCase):
    def setUp(self):
        self.a = Tenant.objects.create(name='Pousada Azul', slug='azul')
        self.b = Tenant.objects.create(name='Hotel Amarelo', slug='amarelo')
        self.user = get_user_model().objects.create_user('atendente', password='testing-strong-password')
        self.other = get_user_model().objects.create_user('outro', password='testing-strong-password')
        self.membership = Membership.objects.create(user=self.user, tenant=self.a, role='owner')
        Membership.objects.create(user=self.other, tenant=self.b, role='owner')
        for tenant, address in ((self.a, '10.66.0.2'), (self.b, '10.66.0.3')):
            with tenant_scope(tenant.pk):
                Router.objects.create(tenant=tenant, tunnel_ip=address, api_user='api-user', encrypted_password=encrypt('admin-secret'), login_url='https://wifi.example.test/login', hotspot_server='hotspot1')
                Branding.objects.create(tenant=tenant)
        self.client.force_login(self.user)

    def data(self, **extra):
        return {'guest_name': 'João', 'username': 'guest-' + uuid.uuid4().hex[:10], 'password': 'visitor-password-42', 'devices': 3, 'duration_hours': 3, 'request_id': uuid.uuid4(), **extra}

    def post_data(self, **extra):
        response = self.client.get(reverse('novainfo:create'))
        token = response.context['form'].initial['request_id']
        return {'guest_name': 'João', 'username': 'guest-' + uuid.uuid4().hex[:10], 'password': 'visitor-password-42', 'devices': 3, 'duration_hours': 3, 'request_id': token, **extra}

    def test_dashboard_scopes_history_and_never_exposes_passwords(self):
        for tenant, actor, name in ((self.a, self.user, 'João'), (self.b, self.other, 'SEGREDO OUTRO TENANT')):
            with tenant_scope(tenant.pk):
                AccessGrant.objects.create(tenant=tenant, created_by=actor, guest_name=name, username=uuid.uuid4().hex, encrypted_password=encrypt('visitor-secret'), devices=1, request_id=uuid.uuid4())
        response = self.client.get('/painel/')
        self.assertContains(response, 'João')
        self.assertNotContains(response, 'SEGREDO OUTRO TENANT')
        self.assertNotContains(response, 'admin-secret')
        self.assertNotContains(response, 'visitor-secret')

    def test_five_menu_destinations(self):
        response = self.client.get('/painel/')
        for name in ('dashboard', 'online', 'create', 'customization', 'account'):
            self.assertContains(response, reverse('novainfo:' + name))
        self.assertNotContains(response, 'Confirmar maioridade')

    def test_login_required_and_no_tenant_no_access(self):
        anonymous = Client()
        self.assertEqual(anonymous.get('/painel/').status_code, 302)
        user = get_user_model().objects.create_user('sem-vinculo')
        anonymous.force_login(user)
        self.assertEqual(anonymous.get('/painel/').status_code, 403)

    @override_settings(NOVAINFO_BASE_DOMAIN='example.test')
    def test_subdomain_must_match_membership(self):
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='azul.example.test').status_code, 200)
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='amarelo.example.test').status_code, 403)
        self.assertEqual(self.client.get('/painel/', HTTP_HOST='inexistente.example.test').status_code, 403)

    @override_settings(NOVAINFO_BASE_DOMAIN='example.test')
    def test_wrong_tenant_login_rejected_and_success_audited(self):
        client = Client()
        response = client.post('/conta/entrar/', {'username': self.user.username, 'password': 'testing-strong-password'}, HTTP_HOST='amarelo.example.test')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)
        response = client.post('/conta/entrar/', {'username': self.user.username, 'password': 'testing-strong-password'}, HTTP_HOST='azul.example.test')
        self.assertEqual(response.status_code, 302)
        with tenant_scope(self.a.pk):
            self.assertTrue(AuditLog.objects.filter(tenant=self.a, action='login').exists())

    @patch('hotspot.views.RouterClient')
    def test_online_uses_authenticated_tenant_only(self, client):
        client.return_value.online.return_value = [{'username': 'joao', 'ip': '10.5.50.10', 'uptime': '25m'}]
        response = self.client.get(reverse('novainfo:online'), {'tenant_id': str(self.b.pk)})
        self.assertContains(response, 'joao')
        self.assertEqual(client.call_args.args[0].tenant_id, self.a.pk)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotContains(response, 'admin-secret')

    @patch('hotspot.views.RouterClient')
    def test_disconnected_never_displays_old_sessions(self, client):
        client.return_value.online.return_value = [{'username': 'old-session', 'ip': '10.0.0.1', 'uptime': '1m'}]
        self.client.get(reverse('novainfo:online'))
        client.return_value.online.side_effect = RouterUnavailable()
        response = self.client.get(reverse('novainfo:online'))
        self.assertContains(response, 'MikroTik desconectado')
        self.assertNotContains(response, 'old-session')
        self.assertEqual(response.context['rows'], [])

    @patch('hotspot.services.RouterClient')
    def test_create_and_whatsapp_and_idempotency(self, client):
        client.return_value.create_user.return_value = '*1'
        data = self.post_data(tenant_id=str(self.b.pk), duration_seconds=999999)
        response = self.client.post(reverse('novainfo:create'), data)
        self.assertContains(response, 'Acesso criado')
        self.assertContains(response, 'https://wa.me/')
        self.assertIn('no-store', response['Cache-Control'])
        with tenant_scope(self.a.pk):
            grant = AccessGrant.objects.get(tenant=self.a)
            self.assertEqual(grant.username, data['username'])
            self.assertEqual(decrypt(grant.encrypted_password), data['password'])
            self.assertEqual(grant.devices, 3)
            self.assertEqual(grant.duration_seconds, 10800)
            self.assertNotEqual(grant.encrypted_password, response.context['password'])
            self.assertTrue(AuditLog.objects.filter(tenant=self.a, action='access_created').exists())
        self.assertEqual(client.call_args.args[0].tenant_id, self.a.pk)
        response = self.client.post(reverse('novainfo:create'), data)
        self.assertContains(response, 'Acesso criado')
        self.assertEqual(client.return_value.create_user.call_count, 1)

    @patch('hotspot.services.RouterClient')
    def test_limits_1_to_6(self, client):
        client.return_value.create_user.return_value = '*2'
        for devices in (1, 2, 3, 4, 5, 6):
            response = self.client.post(reverse('novainfo:create'), self.post_data(devices=devices))
            self.assertContains(response, 'Acesso criado')
        for devices in (0, 7, -1, 'x'):
            response = self.client.post(reverse('novainfo:create'), self.post_data(devices=devices))
            self.assertContains(response, 'errorlist')
        self.assertEqual(client.return_value.create_user.call_count, 6)

    @patch('hotspot.services.RouterClient')
    def test_access_plans_1_3_6_hours_and_confirmation(self, client):
        from urllib.parse import unquote_plus
        client.return_value.create_user.return_value = '*5'
        for hours in (1, 3, 6):
            response = self.client.post(reverse('novainfo:create'), self.post_data(duration_hours=hours))
            self.assertContains(response, 'Acesso criado')
            grant = response.context['grant']
            self.assertEqual(grant.duration_seconds, hours * 3600)
            self.assertContains(response, f'{grant.duration_label} de uso acumulado')
            self.assertIn(f'Tempo: {grant.duration_label} de uso', unquote_plus(response.context['whatsapp']))

    @patch('hotspot.services.RouterClient')
    def test_unsupported_duration_never_reaches_router(self, client):
        for hours in (0, 2, 4, 12, '', 'invalid'):
            response = self.client.post(reverse('novainfo:create'), self.post_data(duration_hours=hours))
            self.assertContains(response, 'errorlist')
        client.assert_not_called()

    @patch('hotspot.services.RouterClient')
    def test_forged_request_token_rejected(self, client):
        response = self.client.post(reverse('novainfo:create'), self.data())
        self.assertContains(response, 'Solicitação inválida')
        client.assert_not_called()

    @patch('hotspot.services.RouterClient')
    def test_chosen_credentials_sent_to_router(self, client):
        client.return_value.create_user.return_value = '*3'
        data = self.post_data(username='joao.quarto-12', password='Senha escolhida 42')
        response = self.client.post(reverse('novainfo:create'), data)
        self.assertContains(response, 'joao.quarto-12')
        self.assertContains(response, 'Senha escolhida 42')
        grant, password = client.return_value.create_user.call_args.args
        self.assertEqual(grant.username, data['username'])
        self.assertEqual(password, data['password'])

    @patch('hotspot.services.RouterClient')
    def test_invalid_credentials_never_reach_router_and_password_not_echoed(self, client):
        for username, password in (('', 'visitor-password-42'), ('a', 'visitor-password-42'),
                                   ('user with spaces', 'visitor-password-42'), ('user', ''), ('user', 'short')):
            response = self.client.post(reverse('novainfo:create'), self.post_data(username=username, password=password))
            self.assertContains(response, 'errorlist')
            self.assertNotContains(response, 'value="visitor-password-42"')
        client.assert_not_called()

    @patch('hotspot.services.RouterClient')
    def test_username_unique_within_tenant_only(self, client):
        client.return_value.create_user.return_value = '*4'
        self.client.post(reverse('novainfo:create'), self.post_data(username='joao'))
        response = self.client.post(reverse('novainfo:create'), self.post_data(username='joao'))
        self.assertContains(response, 'Este usuário já existe neste estabelecimento')
        self.assertEqual(client.return_value.create_user.call_count, 1)
        self.client.force_login(self.other)
        response = self.client.post(reverse('novainfo:create'), self.post_data(username='joao'))
        self.assertContains(response, 'Acesso criado')
        self.assertEqual(client.return_value.create_user.call_count, 2)

    @patch('hotspot.services.RouterClient')
    def test_no_changes_if_preflight_fails(self, client):
        client.return_value.probe.side_effect = RouterUnavailable('Desconectado')
        self.client.post(reverse('novainfo:create'), self.post_data())
        with tenant_scope(self.a.pk):
            self.assertFalse(AccessGrant.objects.filter(tenant=self.a).exists())
        client.return_value.create_user.assert_not_called()

    @patch('hotspot.services.RouterClient')
    def test_uncertain_creation_does_not_retry(self, client):
        client.return_value.create_user.side_effect = RouterUnavailable()
        data = self.post_data()
        self.client.post(reverse('novainfo:create'), data)
        response = self.client.post(reverse('novainfo:create'), data)
        self.assertNotContains(response, 'Acesso criado')
        with tenant_scope(self.a.pk):
            self.assertEqual(AccessGrant.objects.get(tenant=self.a).status, 'uncertain')
        self.assertEqual(client.return_value.create_user.call_count, 1)

    def test_viewer_and_operator_permissions(self):
        self.membership.role = 'viewer'
        self.membership.save()
        self.assertEqual(self.client.get(reverse('novainfo:create')).status_code, 403)
        self.assertEqual(self.client.post(reverse('novainfo:customization'), {'welcome': 'evil'}).status_code, 403)
        self.membership.role = 'operator'
        self.membership.save()
        self.assertEqual(self.client.get(reverse('novainfo:create')).status_code, 200)
        self.assertEqual(self.client.get(reverse('novainfo:customization')).status_code, 403)

    def test_csrf_required_for_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('novainfo:customization'), {'welcome': 'evil'}).status_code, 403)
        self.assertEqual(client.get(reverse('novainfo:logout')).status_code, 405)

    @patch('hotspot.services.RouterClient')
    def test_csrf_same_origin_and_https_referer_work_but_null_and_foreign_fail(self, router):
        router.return_value.create_user.return_value = '*6'
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.get(reverse('novainfo:create'), secure=True)
        self.assertContains(response, '<meta name="referrer" content="same-origin">', html=True)
        self.assertNotContains(response, '<meta name="referrer" content="no-referrer">', html=True)
        token = response.context['form'].initial['request_id']
        data = self.data(request_id=token, csrfmiddlewaretoken=client.cookies['csrftoken'].value)
        for origin in ('null', 'https://other.example.test'):
            response = client.post(reverse('novainfo:create'), data, secure=True, HTTP_ORIGIN=origin)
            self.assertEqual(response.status_code, 403)
        router.assert_not_called()
        response = client.post(reverse('novainfo:create'), data, secure=True, HTTP_ORIGIN='https://testserver')
        self.assertContains(response, 'Acesso criado')
        response = client.post(reverse('novainfo:create'), data, secure=True, HTTP_REFERER='https://testserver/painel/criar-acesso/')
        self.assertContains(response, 'Acesso criado')
        self.assertEqual(router.return_value.create_user.call_count, 1)

    def test_wallpaper_tenant_isolation_and_replacement(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            response = self.client.post(reverse('novainfo:customization'), {'welcome': 'Olá Azul', 'wallpaper': picture(), 'tenant_id': str(self.b.pk)})
            self.assertEqual(response.status_code, 302)
            with tenant_scope(self.a.pk):
                brand_a = Branding.objects.get(tenant=self.a)
                old_name = brand_a.wallpaper.name
                self.assertTrue(old_name.startswith(f'hotspot/{self.a.pk}/'))
            with tenant_scope(self.b.pk):
                self.assertEqual(Branding.objects.get(tenant=self.b).welcome, 'Bem-vindo! Conecte-se ao nosso Wi-Fi.')
            response = Client().get(reverse('novainfo:wallpaper', args=[self.a.pk]))
            self.assertEqual(response['Content-Type'], 'image/webp')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(b''.join(response.streaming_content).startswith(b'RIFF'))
            self.assertEqual(Client().get(reverse('novainfo:wallpaper', args=[self.b.pk])).status_code, 404)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('novainfo:customization'), {'welcome': 'Nova mensagem', 'wallpaper': picture()})
            from django.core.files.storage import default_storage
            self.assertFalse(default_storage.exists(old_name))
            response = Client().get(reverse('novainfo:captive', args=[self.a.pk]))
            self.assertContains(response, 'Nova mensagem')
            self.assertNotContains(response, 'admin-secret')
            self.assertNotContains(response, '10.66.0.2')
            self.assertContains(response, 'https://wifi.example.test/login')

    def test_bad_and_oversized_images_rejected(self):
        invalid = SimpleUploadedFile('x.svg', b'<svg><script>alert(1)</script></svg>', content_type='image/svg+xml')
        form = BrandingForm(data={'welcome': 'Olá'}, files={'wallpaper': invalid})
        self.assertFalse(form.is_valid())
        upload = picture()
        upload.size = 6 * 1024 * 1024
        form = BrandingForm(data={'welcome': 'Olá'}, files={'wallpaper': upload})
        self.assertFalse(form.is_valid())

    def test_account_password_change(self):
        response = self.client.post(reverse('novainfo:account'), {'old_password': 'testing-strong-password', 'new_password1': 'new-testing-strong-password', 'new_password2': 'new-testing-strong-password'})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-testing-strong-password'))
        with tenant_scope(self.a.pk):
            self.assertTrue(AuditLog.objects.filter(tenant=self.a, action='password_changed').exists())

    def test_existing_administration_still_renders(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertEqual(self.client.get('/gestao/').status_code, 200)

    def test_database_constraints(self):
        for devices, duration in ((0, 7200), (7, 7200), (1, 8000)):
            with self.assertRaises(IntegrityError), transaction.atomic(), tenant_scope(self.a.pk):
                AccessGrant.objects.create(tenant=self.a, created_by=self.user, guest_name='x', username=uuid.uuid4().hex, encrypted_password='x', devices=devices, duration_seconds=duration, request_id=uuid.uuid4())


class RouterTests(TestCase):
    def test_blocks_missing_network_and_wrong_route(self):
        with override_settings(NOVAINFO_WIREGUARD_NETWORKS=[]):
            with self.assertRaises(RouterUnavailable):
                verify_tunnel('10.66.0.2')
        with patch('hotspot.router.subprocess.run') as run:
            run.return_value.stdout = json.dumps([{'dev': 'eth0'}])
            with self.assertRaises(RouterUnavailable):
                verify_tunnel('10.66.0.2')
        for address in ('127.0.0.1', '169.254.169.254', '8.8.8.8'):
            with self.assertRaises(RouterUnavailable):
                verify_tunnel(address)

    @patch('hotspot.router.subprocess.run')
    def test_wireguard_interface_type_checked(self, run):
        run.side_effect = [MagicMock(stdout='[{"dev":"wg0"}]'), MagicMock(stdout='[{"linkinfo":{"info_kind":"wireguard"}}]')]
        verify_tunnel('10.66.0.2')
        run.side_effect = [MagicMock(stdout='[{"dev":"wg0"}]'), MagicMock(stdout='[{"linkinfo":{"info_kind":"bridge"}}]')]
        with self.assertRaises(RouterUnavailable):
            verify_tunnel('10.66.0.2')

    @patch('hotspot.router.verify_tunnel')
    @patch('hotspot.router.httpx.Client')
    def test_tls_and_no_redirects_and_no_environment_proxy(self, client, tunnel):
        router = Router(tunnel_ip='10.66.0.2', api_user='operator', encrypted_password=encrypt('secret'))
        client.return_value.__enter__.return_value.request.return_value.json.return_value = []
        RouterClient(router).online()
        self.assertFalse(client.call_args.kwargs['follow_redirects'])
        self.assertFalse(client.call_args.kwargs['trust_env'])
        self.assertIsNot(client.call_args.kwargs['verify'], False)
        tunnel.assert_called_once_with('10.66.0.2')

    def test_user_creation_sends_limits_and_server(self):
        tenant = Tenant(id=uuid.uuid4())
        router = Router(hotspot_server='hotel')
        grant = AccessGrant(tenant=tenant, username='guest', devices=6, request_id=uuid.uuid4())
        client = RouterClient(router)
        with patch.object(client, 'request', side_effect=[[], {'.id': '*1'}, {'.id': '*2'}]) as request:
            self.assertEqual(client.create_user(grant, 'visitor-password'), '*2')
            profile = request.call_args_list[1].kwargs['json']
            payload = request.call_args_list[2].kwargs['json']
            self.assertEqual(profile['shared-users'], '6')
            self.assertEqual(profile['session-timeout'], '1h')
            self.assertEqual(payload['limit-uptime'], '1h')
            self.assertEqual(payload['server'], 'hotel')

    def test_existing_weaker_profile_rejected(self):
        tenant = Tenant(id=uuid.uuid4())
        grant = AccessGrant(tenant=tenant, username='guest', devices=1, request_id=uuid.uuid4())
        client = RouterClient(Router())
        with patch.object(client, 'request', return_value=[{'name': f'ni-{tenant.pk.hex}-1-1h', 'shared-users': '6'}]) as request:
            with self.assertRaises(RouterUnavailable):
                client.create_user(grant, 'password')
            self.assertEqual(request.call_count, 1)

    def test_each_plan_sends_matching_limits_and_distinct_profile(self):
        tenant = Tenant(id=uuid.uuid4())
        client = RouterClient(Router(hotspot_server='hotel'))
        profiles = set()
        for hours in (1, 3, 6):
            grant = AccessGrant(tenant=tenant, username='guest', devices=3, duration_seconds=hours * 3600, request_id=uuid.uuid4())
            with patch.object(client, 'request', side_effect=[[], {'.id': '*1'}, {'.id': '*2'}]) as request:
                client.create_user(grant, 'visitor-password')
                profile = request.call_args_list[1].kwargs['json']
                payload = request.call_args_list[2].kwargs['json']
                self.assertEqual(profile['session-timeout'], f'{hours}h')
                self.assertEqual(payload['limit-uptime'], f'{hours}h')
                self.assertEqual(profile['shared-users'], '3')
                profiles.add(profile['name'])
        self.assertEqual(len(profiles), 3)


class PostgresIsolationTests(TestCase):
    def test_sql_rls_enforces_reads_writes_and_restores_scope(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Exige PostgreSQL para validar RLS real.')
        a = Tenant.objects.create(name='A', slug='rls-a')
        b = Tenant.objects.create(name='B', slug='rls-b')
        with tenant_scope(a.pk):
            Branding.objects.create(tenant=a, welcome='PRIVATE A')
        with tenant_scope(b.pk):
            Branding.objects.create(tenant=b, welcome='PRIVATE B')
        # Dedicated test role is created only in the disposable cluster.
        with connection.cursor() as cursor:
            cursor.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO novainfo_rls_test')
            cursor.execute('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO novainfo_rls_test')
            cursor.execute('SET LOCAL ROLE novainfo_rls_test')
        try:
            self.assertEqual(Branding.objects.count(), 0)
            with tenant_scope(a.pk):
                self.assertEqual(list(Branding.objects.values_list('welcome', flat=True)), ['PRIVATE A'])
                self.assertEqual(Branding.objects.filter(tenant=b).update(welcome='ATTACK'), 0)
                with self.assertRaises(DatabaseError), transaction.atomic():
                    AuditLog.objects.create(tenant=b, action='forged_cross_tenant_write')
                with tenant_scope(b.pk):
                    self.assertEqual(list(Branding.objects.values_list('welcome', flat=True)), ['PRIVATE B'])
                self.assertEqual(list(Branding.objects.values_list('welcome', flat=True)), ['PRIVATE A'])
            self.assertEqual(Branding.objects.count(), 0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET ROLE')


class ProvisionTests(TestCase):
    def test_provision_preserves_existing_password_and_refuses_transfer(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        user = get_user_model().objects.create_user('existing', password='existing-strong-password')
        call_command('provision_tenant', 'first', 'First', user.username, stdout=StringIO())
        membership = Membership.objects.get(user=user)
        self.assertEqual(membership.tenant.slug, 'first')
        user.refresh_from_db()
        self.assertTrue(user.check_password('existing-strong-password'))
        with self.assertRaises(CommandError):
            call_command('provision_tenant', 'second', 'Second', user.username, stdout=StringIO())
        self.assertFalse(Tenant.objects.filter(slug='second').exists())
        membership.refresh_from_db()
        self.assertEqual(membership.tenant.slug, 'first')
        with tenant_scope(membership.tenant_id):
            self.assertTrue(AuditLog.objects.filter(tenant=membership.tenant, action='membership_provisioned').exists())

    def test_export_bridge_contains_only_public_url_and_requires_https(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO
        tenant = Tenant.objects.create(name='Pousada', slug='pousada')
        output = StringIO()
        call_command('export_hotspot_login', 'pousada', origin='https://portal.example.test', stdout=output)
        self.assertIn(f'https://portal.example.test/hotspot/{tenant.pk}/', output.getvalue())
        self.assertNotIn('password', output.getvalue())
        with self.assertRaises(CommandError):
            call_command('export_hotspot_login', 'pousada', origin='http://portal.example.test', stdout=StringIO())
