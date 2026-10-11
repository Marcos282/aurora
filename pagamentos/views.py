import hashlib
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from anunciantes.models import Advertiser
from assinaturas.models import Plan
from .models import Payment, WebhookReceipt
from .services import PaymentUnavailable, check_enabled, provider_request, reconcile, start_checkout, validate_signature

logger = logging.getLogger(__name__)


@login_required
@require_POST
def checkout(request, plan_id):
    plan = get_object_or_404(Plan, pk=plan_id, active=True)
    advertiser = get_object_or_404(Advertiser, user=request.user)
    try:
        check_enabled()
        with transaction.atomic():
            Advertiser.objects.select_for_update().get(pk=advertiser.pk)
            payment = Payment.objects.filter(advertiser=advertiser, plan=plan, status="pending").order_by("-created_at").first()
            if not payment:
                payment = Payment.objects.create(advertiser=advertiser, plan=plan, amount=plan.price,
                                                 days=plan.days, tier=plan.tier, priority=plan.priority)
        url = payment.checkout_url or start_checkout(payment)
    except PaymentUnavailable as exc:
        messages.error(request, str(exc))
        return redirect("panel")
    return redirect(url)


@csrf_exempt
@require_POST
def webhook(request):
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise ValidationError("Evento invalido.")
        provider_id = request.GET.get("data.id", "")
        if not provider_id.isdigit() or str(payload["data"].get("id")) != provider_id:
            raise ValidationError("Identificador invalido.")
        validate_signature(request, provider_id)
        event_key = hashlib.sha256(
            (provider_id + request.headers.get("x-signature", "") + request.headers.get("x-request-id", "")).encode()
        ).hexdigest()
        if WebhookReceipt.objects.filter(event_key=event_key).exists():
            return JsonResponse({"received": True})
        data = provider_request("GET", "/v1/payments/" + provider_id)
        if str(data.get("id")) != provider_id:
            raise ValidationError("Resposta do provedor inconsistente.")
        reconcile(data)
        WebhookReceipt.objects.get_or_create(event_key=event_key, defaults={"provider_id": provider_id})
    except PaymentUnavailable as exc:
        logger.warning("Webhook indisponivel: %s", exc)
        return JsonResponse({"error": str(exc)}, status=503)
    except (ValueError, ValidationError) as exc:
        logger.warning("Webhook rejeitado (%s)", type(exc).__name__)
        return JsonResponse({"error": "Webhook invalido."}, status=400)
    return JsonResponse({"received": True})
