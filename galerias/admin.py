from django.contrib import admin

from moderacao.models import AuditEvent
from .models import Photo


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "advertiser", "consent", "approved", "order")
    readonly_fields = tuple(field.name for field in Photo._meta.fields)
    actions = ["approve_photos", "reject_photos"]

    @admin.action(description="Aprovar fotos revisadas com consentimento")
    def approve_photos(self, request, queryset):
        for photo in queryset.filter(consent=True):
            photo.approved = True
            photo.save(update_fields=["approved"])
            AuditEvent.objects.create(actor=request.user, advertiser=photo.advertiser, action="photo_approved")

    @admin.action(description="Reprovar fotos")
    def reject_photos(self, request, queryset):
        queryset.update(approved=False)

    def has_add_permission(self, request):
        return False
