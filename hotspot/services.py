import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from PIL import Image, ImageOps

from .models import AccessGrant, AuditLog, Branding, Router
from .router import RouterClient
from .security import RouterUnavailable, decrypt, encrypt


def router_for(tenant):
    try:
        return Router.objects.get(tenant=tenant, enabled=True)
    except Router.DoesNotExist:
        raise RouterUnavailable('MikroTik não configurado para este estabelecimento.') from None


def issue_access(tenant, actor, data):
    existing = AccessGrant.objects.filter(tenant=tenant, request_id=data['request_id']).first()
    if existing:
        if existing.status == 'active' and existing.created_by_id == actor.pk:
            return existing, decrypt(existing.encrypted_password)
        raise RouterUnavailable('Esta solicitação requer conferência técnica. Não reenvie a criação.')
    username = data['username']
    password = data['password']
    if data['duration_hours'] not in (1, 3, 6):
        raise RouterUnavailable('Escolha um plano de 1, 3 ou 6 horas.')
    if AccessGrant.objects.filter(tenant=tenant, username=username).exists():
        raise RouterUnavailable('Este usuário já existe neste estabelecimento. Escolha outro nome.')
    client = RouterClient(router_for(tenant))
    client.probe()
    with transaction.atomic():
        try:
            grant, created = AccessGrant.objects.get_or_create(
                tenant=tenant, request_id=data['request_id'],
                defaults={'created_by': actor, 'guest_name': data['guest_name'], 'devices': data['devices'],
                          'duration_seconds': data['duration_hours'] * 3600,
                          'username': username, 'encrypted_password': encrypt(password)},
            )
        except IntegrityError:
            raise RouterUnavailable('Este usuário já existe neste estabelecimento. Escolha outro nome.') from None
        if not created:
            if grant.status == 'active' and grant.created_by_id == actor.pk:
                return grant, decrypt(grant.encrypted_password)
            raise RouterUnavailable('Solicitação já recebida. Aguarde a conferência técnica.')
        try:
            grant.router_id_value = client.create_user(grant, password)
        except RouterUnavailable:
            grant.status = 'uncertain'
            grant.save(update_fields=['status'])
            AuditLog.objects.create(tenant=tenant, actor=actor, action='access_confirmation_required', object_id=str(grant.pk))
        else:
            grant.status = 'active'
            grant.save(update_fields=['status', 'router_id_value'])
            AuditLog.objects.create(tenant=tenant, actor=actor, action='access_created', object_id=str(grant.pk))
    if grant.status != 'active':
        raise RouterUnavailable('Não foi possível confirmar a criação. Solicite conferência técnica antes de tentar novamente.')
    return grant, password


def save_branding(tenant, actor, form):
    new_name = None
    old_name = form.instance.wallpaper.name
    upload = form.cleaned_data.get('wallpaper')
    if upload and hasattr(upload, 'content_type'):
        with Image.open(upload) as image:
            normalized = ImageOps.exif_transpose(image).convert('RGB')
            normalized.thumbnail((2560, 2560))
            # Recreate pixels to remove metadata from the uploaded image.
            clean = Image.new('RGB', normalized.size)
            clean.paste(normalized)
            output = BytesIO()
            clean.save(output, 'WEBP', quality=85)
        new_name = default_storage.save(f'hotspot/{tenant.pk}/{uuid.uuid4().hex}.webp', ContentFile(output.getvalue()))
    try:
        with transaction.atomic():
            # Serialize updates to avoid conflicting writes to the tenant's image.
            from .models import Tenant
            Tenant.objects.select_for_update().get(pk=tenant.pk)
            branding, _ = Branding.objects.get_or_create(tenant=tenant)
            old_name = branding.wallpaper.name
            branding.welcome = form.cleaned_data['welcome']
            if new_name:
                branding.wallpaper = new_name
            branding.save()
            AuditLog.objects.create(tenant=tenant, actor=actor, action='branding_updated')
            if new_name and old_name:
                transaction.on_commit(lambda: default_storage.delete(old_name))
    except Exception:
        if new_name:
            default_storage.delete(new_name)
        raise
    return branding
