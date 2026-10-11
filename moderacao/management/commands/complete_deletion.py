import uuid

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from anunciantes.models import Advertiser
from moderacao.models import AuditEvent, DeletionRequest, IdentityCheck


class Command(BaseCommand):
    help = "Anonimiza perfil com exclusao solicitada; conserva registros financeiros para retencao legal."

    def add_arguments(self, parser):
        parser.add_argument("request_id", type=int)
        parser.add_argument("--confirm-legal-review", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm_legal_review"]:
            raise CommandError("Revise obrigacoes de retencao e informe --confirm-legal-review.")
        with transaction.atomic():
            try:
                request = DeletionRequest.objects.select_for_update().get(pk=options["request_id"], completed_at__isnull=True)
            except DeletionRequest.DoesNotExist as exc:
                raise CommandError("Solicitacao aberta nao encontrada.") from exc
            advertiser = Advertiser.objects.select_for_update().get(pk=request.advertiser_id)
            paths = list(advertiser.photos.values_list("image", flat=True))
            advertiser.photos.all().delete()
            identity = IdentityCheck.objects.filter(advertiser=advertiser).first()
            if identity:
                path = (settings.PRIVATE_ROOT / identity.encrypted_path).resolve()
                if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()):
                    raise CommandError("Caminho privado invalido; exclusao interrompida.")
                transaction.on_commit(lambda: path.unlink(missing_ok=True))
                identity.delete()
            advertiser.name = "Conta excluida"
            advertiser.slug = "excluido-" + uuid.uuid4().hex
            advertiser.contact = advertiser.description = advertiser.summary = ""
            advertiser.city = advertiser.neighborhood = ""
            advertiser.available = advertiser.active = False
            advertiser.status = "suspended"
            advertiser.save()
            user = advertiser.user
            user.username = "excluido_" + uuid.uuid4().hex
            user.email = user.first_name = user.last_name = ""
            user.is_active = False
            user.set_unusable_password()
            user.save()
            advertiser.daily_views.all().delete()
            request.completed_at = timezone.now()
            request.save(update_fields=["completed_at"])
            AuditEvent.objects.create(actor=None, advertiser=advertiser, action="account_anonymized_after_legal_review")
            for name in paths:
                transaction.on_commit(lambda filename=name: default_storage.delete(filename))
        self.stdout.write(self.style.SUCCESS("Perfil anonimizado; fotos e documento removidos. Registros financeiros preservados."))
