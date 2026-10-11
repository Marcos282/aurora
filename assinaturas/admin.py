from django.contrib import admin

from .models import Plan, Subscription

admin.site.register(Plan)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("advertiser", "plan", "starts_at", "ends_at", "revoked")
    readonly_fields = tuple(field.name for field in Subscription._meta.fields if field.name != "revoked")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
