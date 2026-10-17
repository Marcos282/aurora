from django.conf import settings
from django.http import HttpResponseForbidden

from .models import Membership, Tenant
from .security import tenant_scope


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        request.membership = None
        # Administration keeps its existing authentication and behavior.
        if request.path.startswith(('/admin/', '/gestao/', '/documentos/', '/static/')):
            return self.get_response(request)
        host = request.get_host().split(':')[0].lower().rstrip('.')
        domain = settings.NOVAINFO_BASE_DOMAIN
        hostname_tenant = None
        if domain and host.endswith('.' + domain):
            slug = host[:-(len(domain) + 1)]
            hostname_tenant = Tenant.objects.filter(slug=slug, active=True).first()
            if not hostname_tenant:
                return HttpResponseForbidden('Estabelecimento indisponível.')
        if request.user.is_authenticated:
            membership = Membership.objects.select_related('tenant').filter(user=request.user, active=True, tenant__active=True).first()
            if membership:
                if hostname_tenant and hostname_tenant.pk != membership.tenant_id:
                    return HttpResponseForbidden('Sem permissão para este estabelecimento.')
                request.membership = membership
                request.tenant = membership.tenant
        request.hostname_tenant = hostname_tenant
        if request.tenant:
            with tenant_scope(request.tenant.pk):
                return self.get_response(request)
        return self.get_response(request)
