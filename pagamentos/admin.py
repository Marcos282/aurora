from django.contrib import admin

from .models import Payment, WebhookReceipt


@admin.register(Payment, WebhookReceipt)
class PaymentAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
