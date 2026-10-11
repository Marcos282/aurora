import hashlib
import hmac
import logging
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from assinaturas.models import Subscription
from .models import Payment

logger = logging.getLogger(__name__)


class PaymentUnavailable(Exception):
    pass


def check_enabled():
    if not all((settings.PAYMENTS_ENABLED, settings.PAYMENT_PROVIDER_APPROVED,
                settings.MERCADOPAGO_ACCESS_TOKEN, settings.MERCADOPAGO_WEBHOOK_SECRET)):
        raise PaymentUnavailable("Pagamentos indisponiveis ate aprovacao da atividade e configuracao do provedor.")


def provider_request(method: str, path: str, **kwargs):
    check_enabled()
    try:
        with httpx.Client(timeout=20, trust_env=False) as client:
            response = client.request(method, "https://api.mercadopago.com" + path, headers={
                "Authorization": "Bearer " + settings.MERCADOPAGO_ACCESS_TOKEN,
                **kwargs.pop("headers", {}),
            }, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Resposta invalida.")
            return data
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Falha de comunicacao com provedor de pagamento (%s)", type(exc).__name__)
        raise PaymentUnavailable("Provedor indisponivel. Tente novamente mais tarde.") from exc


def start_checkout(payment: Payment) -> str:
    data = provider_request("POST", "/checkout/preferences", headers={"X-Idempotency-Key": str(payment.pk)}, json={
        "external_reference": str(payment.pk),
        "items": [{"id": str(payment.plan_id), "title": payment.plan.name, "quantity": 1,
                   "currency_id": "BRL", "unit_price": float(payment.amount)}],
        "notification_url": settings.PUBLIC_ORIGIN + "/pagamentos/webhook/",
        "back_urls": {key: settings.PUBLIC_ORIGIN + "/painel/" for key in ("success", "pending", "failure")},
    })
    url = data.get("init_point", "")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or not (
        parts.hostname == "mercadopago.com.br" or parts.hostname.endswith(".mercadopago.com.br")
    ):
        raise PaymentUnavailable("Provedor retornou um checkout invalido.")
    Payment.objects.filter(pk=payment.pk).update(checkout_url=url)
    return url


def validate_signature(request, provider_id: str):
    check_enabled()
    signature = request.headers.get("x-signature", "")
    parts = dict(item.strip().split("=", 1) for item in signature.split(",") if "=" in item)
    timestamp = parts.get("ts", "")
    request_id = request.headers.get("x-request-id", "")
    if not timestamp.isdigit() or not request_id or abs(time.time() - int(timestamp)) > 300:
        raise ValidationError("Webhook expirado ou sem identificacao.")
    manifest = f"id:{provider_id.lower()};request-id:{request_id};ts:{timestamp};"
    expected = hmac.new(settings.MERCADOPAGO_WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts.get("v1", "")):
        raise ValidationError("Assinatura do webhook invalida.")


def reconcile(data: dict):
    reference = data.get("external_reference")
    try:
        amount = Decimal(str(data.get("transaction_amount")))
        if not amount.is_finite():
            raise InvalidOperation
    except InvalidOperation as exc:
        raise ValidationError("Valor de pagamento invalido.") from exc
    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(pk=reference)
        except (Payment.DoesNotExist, ValueError, ValidationError) as exc:
            raise ValidationError("Pedido desconhecido.") from exc
        if data.get("currency_id") != "BRL" or amount != payment.amount:
            raise ValidationError("Valor ou moeda diferente do pedido.")
        provider_id = str(data.get("id", ""))
        if not provider_id.isdigit() or (payment.provider_id and payment.provider_id != provider_id):
            raise ValidationError("Identificador de pagamento inconsistente.")
        status = data.get("status")
        if status not in {"approved", "pending", "in_process", "rejected", "cancelled", "refunded", "charged_back"}:
            raise ValidationError("Status desconhecido.")
        if status == "approved" and payment.status in {"refunded", "charged_back"}:
            raise ValidationError("Pagamento revertido nao pode ser reativado.")
        if status in {"refunded", "charged_back", "cancelled"}:
            Subscription.objects.filter(payment=payment).update(revoked=True)
        elif status == "approved" and payment.confirmed_at is None:
            # Lock the advertiser to serialize simultaneous renewals.
            from anunciantes.models import Advertiser
            Advertiser.objects.select_for_update().get(pk=payment.advertiser_id)
            now = timezone.now()
            latest = Subscription.objects.filter(
                advertiser=payment.advertiser, tier=payment.tier, revoked=False, ends_at__gt=now,
            ).order_by("-ends_at").first()
            starts = latest.ends_at if latest else now
            Subscription.objects.create(
                advertiser=payment.advertiser, plan=payment.plan, payment=payment,
                tier=payment.tier, priority=payment.priority, starts_at=starts,
                ends_at=starts + timedelta(days=payment.days),
            )
            payment.confirmed_at = now
        payment.status = status
        payment.provider_id = provider_id
        payment.save(update_fields=["status", "provider_id", "confirmed_at"])
        return payment
