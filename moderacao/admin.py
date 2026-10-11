from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import AuditEvent, DeletionRequest, IdentityCheck, Report
from .services import adult_on


class IdentityForm(forms.ModelForm):
    class Meta:
        model = IdentityCheck
        fields = ["status", "birth_date", "notes"]

    def clean(self):
        data = super().clean()
        if data.get("status") == "verified":
            birth = data.get("birth_date")
            if not birth or not adult_on(birth, timezone.localdate()) or not self.instance.consent:
                raise forms.ValidationError("Documento, consentimento e data de nascimento adulta sao obrigatorios.")
        return data


@admin.register(IdentityCheck)
class IdentityAdmin(admin.ModelAdmin):
    form = IdentityForm
    list_display = ("advertiser", "status", "submitted_at")
    readonly_fields = ("advertiser", "document_link", "consent", "submitted_at", "reviewed_by", "reviewed_at")
    fields = readonly_fields + ("birth_date", "status", "notes")

    @admin.display(description="Documento privado")
    def document_link(self, obj):
        return format_html('<a href="{}">Baixar documento criptografado para revisao</a>', reverse("identity-document", args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        obj.reviewed_by = request.user
        obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
        AuditEvent.objects.create(actor=request.user, advertiser=obj.advertiser, action="identity_" + obj.status)

    def has_add_permission(self, request):
        return False


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("advertiser", "reason", "status", "created_at")
    readonly_fields = ("advertiser", "reason", "details", "created_at")
    list_filter = ("status", "reason")


@admin.register(AuditEvent, DeletionRequest)
class RecordAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
