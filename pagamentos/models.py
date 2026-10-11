import uuid

from django.db import models

from anunciantes.models import Advertiser
from assinaturas.models import Plan


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    advertiser = models.ForeignKey(Advertiser, on_delete=models.PROTECT, related_name="payments")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    days = models.PositiveSmallIntegerField()
    tier = models.CharField(max_length=10)
    priority = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, default="pending")
    provider_id = models.CharField(max_length=80, unique=True, null=True, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class WebhookReceipt(models.Model):
    event_key = models.CharField(max_length=64, unique=True)
    provider_id = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
