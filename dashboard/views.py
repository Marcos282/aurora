from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from anunciantes.forms import ProfileForm
from anunciantes.models import Advertiser
from assinaturas.models import Plan, Subscription
from galerias.models import Photo
from galerias.services import store_photo
from moderacao.models import AuditEvent, DeletionRequest, IdentityCheck, Report
from moderacao.services import store_identity
from pagamentos.models import Payment


@login_required
def panel(request):
    advertiser = Advertiser.objects.filter(user=request.user).first()
    form = ProfileForm(request.POST or None, instance=advertiser)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if advertiser:
                current = Advertiser.objects.select_for_update().get(pk=advertiser.pk)
                if current.status == "suspended" or DeletionRequest.objects.filter(advertiser=current, completed_at__isnull=True).exists():
                    messages.error(request, "Perfil suspenso ou com exclusao solicitada. Contate a moderacao.")
                    return redirect("panel")
                form = ProfileForm(request.POST, instance=current)
                if not form.is_valid():
                    return render(request, "dashboard/panel.html", {"form": form, "advertiser": current})
            updated = form.save(commit=False)
            updated.user = request.user
            if advertiser:
                updated.revision += 1
            updated.status = "pending"
            updated.updated_at = timezone.now()
            updated.save()
            AuditEvent.objects.create(actor=request.user, advertiser=updated, action="profile_updated")
        messages.success(request, "Perfil salvo e enviado para moderacao. Alteracoes nao sao publicadas automaticamente.")
        return redirect("panel")
    active = Subscription.objects.filter(
        advertiser=advertiser, revoked=False, starts_at__lte=timezone.now(), ends_at__gt=timezone.now(),
    ).order_by("-priority", "-ends_at").first() if advertiser else None
    views = (advertiser.daily_views.aggregate(total=Sum("count"))["total"] or 0) if advertiser else 0
    return render(request, "dashboard/panel.html", {
        "form": form, "advertiser": advertiser, "subscription": active, "views": views,
        "plans": Plan.objects.filter(active=True), "payments_enabled": settings.PAYMENTS_ENABLED and settings.PAYMENT_PROVIDER_APPROVED,
        "payments": advertiser.payments.order_by("-created_at")[:20] if advertiser else [],
        "identity_enabled": bool(settings.IDENTITY_ENCRYPTION_KEY),
    })


def owned(request):
    return get_object_or_404(Advertiser, user=request.user)


@login_required
@require_POST
def upload_photo(request):
    advertiser = owned(request)
    if request.POST.get("consent") != "yes" or "image" not in request.FILES:
        messages.error(request, "Selecione uma imagem e confirme consentimento de todas as pessoas retratadas.")
        return redirect("panel")
    name = None
    try:
        with transaction.atomic():
            advertiser = Advertiser.objects.select_for_update().get(pk=advertiser.pk)
            if advertiser.status == "suspended" or advertiser.photos.count() >= 12:
                raise ValidationError("Perfil suspenso ou limite de 12 fotos atingido.")
            name = store_photo(request.FILES["image"])
            Photo.objects.create(advertiser=advertiser, image=name, order=advertiser.photos.count(), consent=True, consent_at=timezone.now())
            advertiser.revision += 1
            advertiser.status = "pending"
            advertiser.save(update_fields=["revision", "status"])
            AuditEvent.objects.create(actor=request.user, advertiser=advertiser, action="photo_added")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    except Exception:
        if name:
            from django.core.files.storage import default_storage
            default_storage.delete(name)
        raise
    else:
        messages.success(request, "Foto convertida para WebP e enviada para moderacao.")
    return redirect("panel")


@login_required
@require_POST
def photo_action(request, photo_id):
    with transaction.atomic():
        advertiser = get_object_or_404(Advertiser.objects.select_for_update(), user=request.user)
        photo = get_object_or_404(Photo, pk=photo_id, advertiser=advertiser)
        action = request.POST.get("action")
        if action == "delete":
            name = photo.image.name
            photo.delete()
            from django.core.files.storage import default_storage
            transaction.on_commit(lambda: default_storage.delete(name))
        elif action in {"up", "down"}:
            ordered = list(advertiser.photos.order_by("order", "pk"))
            index = next(i for i, item in enumerate(ordered) if item.pk == photo.pk)
            destination = index + (-1 if action == "up" else 1)
            if 0 <= destination < len(ordered):
                ordered[index], ordered[destination] = ordered[destination], ordered[index]
                for order, item in enumerate(ordered):
                    item.order = order
                Photo.objects.bulk_update(ordered, ["order"])
        else:
            messages.error(request, "Acao de foto invalida.")
            return redirect("panel")
        advertiser.revision += 1
        if advertiser.status != "suspended":
            advertiser.status = "pending"
        advertiser.save(update_fields=["revision", "status"])
        AuditEvent.objects.create(actor=request.user, advertiser=advertiser, action="photo_" + action)
    return redirect("panel")


@login_required
@require_POST
def toggle(request):
    with transaction.atomic():
        advertiser = get_object_or_404(Advertiser.objects.select_for_update(), user=request.user)
        if DeletionRequest.objects.filter(advertiser=advertiser, completed_at__isnull=True).exists():
            messages.error(request, "Exclusao solicitada; o perfil nao pode ser reativado.")
        else:
            advertiser.active = not advertiser.active
            advertiser.save(update_fields=["active"])
            AuditEvent.objects.create(actor=request.user, advertiser=advertiser, action="visibility_changed")
    return redirect("panel")


@login_required
@require_POST
def delete_account(request):
    advertiser = owned(request)
    if request.POST.get("confirm") != "EXCLUIR":
        messages.error(request, "Digite EXCLUIR para solicitar exclusao.")
        return redirect("panel")
    with transaction.atomic():
        advertiser = Advertiser.objects.select_for_update().get(pk=advertiser.pk)
        advertiser.active = False
        advertiser.save(update_fields=["active"])
        if not DeletionRequest.objects.filter(advertiser=advertiser, completed_at__isnull=True).exists():
            DeletionRequest.objects.create(advertiser=advertiser)
        AuditEvent.objects.create(actor=request.user, advertiser=advertiser, action="deletion_requested")
    messages.success(request, "Anuncio ocultado. A equipe tratara a exclusao e eventuais obrigacoes de retencao.")
    return redirect("panel")


@login_required
@require_POST
def submit_identity(request):
    advertiser = owned(request)
    if request.POST.get("consent") != "yes" or "document" not in request.FILES:
        messages.error(request, "Envie um documento e autorize a verificacao de identidade.")
        return redirect("panel")
    try:
        with transaction.atomic():
            advertiser = Advertiser.objects.select_for_update().get(pk=advertiser.pk)
            if IdentityCheck.objects.filter(advertiser=advertiser).exists():
                raise ValidationError("Ja existe uma verificacao. Solicite orientacao a moderacao.")
            name = store_identity(request.FILES["document"])
            IdentityCheck.objects.create(advertiser=advertiser, encrypted_path=name, consent=True)
            AuditEvent.objects.create(actor=request.user, advertiser=advertiser, action="identity_submitted")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, "Documento criptografado recebido. A publicacao depende de verificacao manual.")
    return redirect("panel")


@user_passes_test(lambda user: user.is_active and user.is_staff)
@require_GET
def admin_dashboard(request):
    month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return render(request, "dashboard/admin.html", {
        "revenue": Payment.objects.filter(status="approved", confirmed_at__gte=month).aggregate(total=Sum("amount"))["total"] or 0,
        "active": Advertiser.objects.filter(active=True, status="approved").count(),
        "pending": Advertiser.objects.filter(status="pending").count(),
        "expired": Subscription.objects.filter(ends_at__lte=timezone.now(), revoked=False).count(),
        "reports": Report.objects.filter(status="open").count(),
    })
