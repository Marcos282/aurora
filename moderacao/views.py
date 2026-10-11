
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from rankings.services import public_advertisers
from .models import AuditEvent, IdentityCheck, Report


@require_http_methods(["GET", "POST"])
def report(request, slug):
    advertiser = get_object_or_404(public_advertisers(), slug=slug)
    if request.method == "POST":
        reason = request.POST.get("reason", "")
        details = request.POST.get("details", "").strip()
        if reason not in dict(Report._meta.get_field("reason").choices) or not 10 <= len(details) <= 2000:
            return render(request, "core/report.html", {"advertiser": advertiser, "error": True}, status=400)
        if request.session.get("reported_" + str(advertiser.pk)):
            messages.error(request, "Sua denuncia ja foi recebida para este perfil.")
            return redirect("profile", slug=slug)
        Report.objects.create(advertiser=advertiser, reason=reason, details=details)
        request.session["reported_" + str(advertiser.pk)] = True
        messages.success(request, "Denuncia recebida pela moderacao.")
        return redirect("home")
    return render(request, "core/report.html", {"advertiser": advertiser})


@user_passes_test(lambda user: user.is_active and user.has_perm("moderacao.view_identitycheck"))
@require_GET
def identity_document(request, pk):
    identity = get_object_or_404(IdentityCheck, pk=pk)
    path = (settings.PRIVATE_ROOT / identity.encrypted_path).resolve()
    if not path.is_relative_to(settings.PRIVATE_ROOT.resolve()) or not path.is_file():
        raise Http404
    payload = Fernet(settings.IDENTITY_ENCRYPTION_KEY.encode()).decrypt(path.read_bytes())
    AuditEvent.objects.create(actor=request.user, advertiser=identity.advertiser, action="identity_document_accessed")
    response = HttpResponse(payload, content_type="image/webp")
    response["Content-Disposition"] = 'attachment; filename="verificacao.webp"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
