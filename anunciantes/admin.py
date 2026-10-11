from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

from moderacao.models import AuditEvent
from moderacao.services import approve
from .models import Advertiser


@admin.register(Advertiser)
class AdvertiserAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "age", "status", "active")
    search_fields = ("name", "city", "user__username")
    list_filter = ("status", "state", "active")
    readonly_fields = tuple(field.name for field in Advertiser._meta.fields)
    actions = ["approve_profiles", "suspend_profiles"]

    @admin.action(description="Aprovar perfis com identidade e fotos verificadas")
    def approve_profiles(self, request, queryset):
        for pk in queryset.values_list("pk", flat=True):
            try:
                with transaction.atomic():
                    advertiser = Advertiser.objects.select_for_update().get(pk=pk)
                    approve(advertiser, request.user)
            except ValidationError as exc:
                self.message_user(request, f"Perfil {pk}: {'; '.join(exc.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"Perfil {pk} aprovado.", messages.SUCCESS)

    @admin.action(description="Suspender perfis selecionados")
    def suspend_profiles(self, request, queryset):
        with transaction.atomic():
            for advertiser in queryset.select_for_update():
                advertiser.status = "suspended"
                advertiser.save(update_fields=["status"])
                AuditEvent.objects.create(actor=request.user, advertiser=advertiser, action="profile_suspended")

    def has_add_permission(self, request):
        return False
