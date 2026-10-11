import uuid
from datetime import date

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import AuditEvent


def adult_on(birth_date: date, today: date) -> bool:
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day)) >= 18


def store_identity(upload) -> str:
    if not settings.IDENTITY_ENCRYPTION_KEY:
        raise ValidationError("Recebimento de documentos indisponivel: configure o armazenamento criptografado.")
    from galerias.services import store_photo
    from django.core.files.storage import default_storage

    name = store_photo(upload)
    try:
        with default_storage.open(name, "rb") as image:
            payload = Fernet(settings.IDENTITY_ENCRYPTION_KEY.encode()).encrypt(image.read())
        root = settings.PRIVATE_ROOT
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = root / (uuid.uuid4().hex + ".enc")
        with target.open("xb") as output:
            target.chmod(0o600)
            output.write(payload)
        return target.name
    finally:
        default_storage.delete(name)


def approve(advertiser, actor):
    identity = getattr(advertiser, "identity", None)
    if not identity or identity.status != "verified" or not identity.birth_date or not adult_on(identity.birth_date, timezone.localdate()):
        raise ValidationError("Verifique identidade e maioridade antes de aprovar.")
    photos = list(advertiser.photos.all())
    if not photos or any(not photo.approved or not photo.consent for photo in photos):
        raise ValidationError("Todas as fotos precisam de consentimento e moderacao.")
    if advertiser.contact and not advertiser.contact_consent:
        raise ValidationError("Contato sem consentimento.")
    advertiser.status = "approved"
    advertiser.approved_revision = advertiser.revision
    advertiser.save(update_fields=["status", "approved_revision"])
    AuditEvent.objects.create(actor=actor, advertiser=advertiser, action="profile_approved")
