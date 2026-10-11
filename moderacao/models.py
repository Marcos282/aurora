from django.conf import settings
from django.db import models

from anunciantes.models import Advertiser


class IdentityCheck(models.Model):
    advertiser = models.OneToOneField(Advertiser, on_delete=models.CASCADE, related_name="identity")
    encrypted_path = models.CharField(max_length=300)
    status = models.CharField(max_length=12, choices=[("pending", "Pendente"), ("verified", "Verificado"), ("rejected", "Reprovado")], default="pending")
    birth_date = models.DateField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    consent = models.BooleanField(default=False)
    notes = models.CharField(max_length=500, blank=True)


class Report(models.Model):
    advertiser = models.ForeignKey(Advertiser, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=30, choices=[
        ("age", "Suspeita de menoridade"), ("consent", "Ausencia de consentimento"),
        ("fraud", "Fraude ou identidade falsa"), ("abuse", "Exploracao ou abuso"), ("other", "Outro motivo"),
    ])
    details = models.TextField(max_length=2000)
    status = models.CharField(max_length=12, choices=[("open", "Aberta"), ("resolved", "Resolvida")], default="open")
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    advertiser = models.ForeignKey(Advertiser, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)


class DeletionRequest(models.Model):
    advertiser = models.ForeignKey(Advertiser, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
