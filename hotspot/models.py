import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('Estabelecimento', max_length=120)
    slug = models.SlugField(unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    role = models.CharField(max_length=12, choices=[('owner', 'Responsável'), ('operator', 'Atendente'), ('viewer', 'Consulta')], default='viewer')
    active = models.BooleanField(default=True)

    @property
    def can_create(self):
        return self.role in ('owner', 'operator')

    @property
    def can_customize(self):
        return self.role == 'owner'


class Router(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.PROTECT)
    tunnel_ip = models.GenericIPAddressField(protocol='IPv4', unique=True)
    https_port = models.PositiveIntegerField(default=443, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    api_user = models.CharField(max_length=80)
    encrypted_password = models.TextField()
    login_url = models.URLField(max_length=300, help_text='URL HTTPS de login do Hotspot, acessível aos hóspedes.')
    hotspot_server = models.CharField(max_length=80, default='hotspot1')
    enabled = models.BooleanField(default=True)

    def clean(self):
        from .security import validate_login_url
        validate_login_url(self.login_url)
        if not self.hotspot_server.strip() or self.hotspot_server.lower() == 'all':
            raise ValidationError({'hotspot_server': 'Informe um servidor Hotspot específico.'})


class Branding(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE)
    welcome = models.CharField('Mensagem de boas-vindas', max_length=160, default='Bem-vindo! Conecte-se ao nosso Wi-Fi.')
    wallpaper = models.ImageField(upload_to='hotspot/', blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class AccessGrant(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    guest_name = models.CharField(max_length=100)
    username = models.CharField(max_length=80)
    encrypted_password = models.TextField()
    devices = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(6)])
    duration_seconds = models.PositiveIntegerField(default=3600, editable=False)
    request_id = models.UUIDField()
    status = models.CharField(max_length=12, choices=[('pending', 'Em criação'), ('active', 'Criado'), ('uncertain', 'Requer conferência')], default='pending')
    router_id_value = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(devices__gte=1, devices__lte=6), name='hotspot_devices_1_6'),
            # Keep historical 2-hour grants without rewriting issued credentials.
            models.CheckConstraint(condition=Q(duration_seconds__in=[3600, 7200, 10800, 21600]), name='hotspot_duration_supported'),
            models.UniqueConstraint(fields=['tenant', 'request_id'], name='hotspot_idempotent_request'),
            models.UniqueConstraint(fields=['tenant', 'username'], name='hotspot_tenant_username'),
        ]

    @property
    def duration_label(self):
        hours = self.duration_seconds // 3600
        return f'{hours} hora' + ('s' if hours != 1 else '')


class AuditLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
