import uuid
from functools import wraps
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from accounts.views import PortalLoginView
from .forms import AccessForm, BrandingForm
from .models import AccessGrant, AuditLog, Branding, Tenant
from .router import OFFLINE, RouterClient
from .security import RouterUnavailable, tenant_scope, validate_login_url
from .services import issue_access, router_for, save_branding


class TenantLoginView(PortalLoginView):
    template_name = 'tenant/login.html'
    next_page = '/painel/'

    def form_valid(self, form):
        from .models import Membership
        membership = Membership.objects.select_related('tenant').filter(user=form.get_user(), active=True, tenant__active=True).first()
        host_tenant = getattr(self.request, 'hostname_tenant', None)
        if host_tenant and (not membership or membership.tenant_id != host_tenant.pk):
            form.add_error(None, 'Esta conta não tem acesso a este estabelecimento.')
            return self.form_invalid(form)
        response = super().form_valid(form)
        if membership:
            with tenant_scope(membership.tenant_id):
                AuditLog.objects.create(tenant=membership.tenant, actor=form.get_user(), action='login')
        return response


def tenant_required(permission=None):
    def decorate(view):
        @login_required
        @never_cache
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.tenant or not request.membership:
                return render(request, 'tenant/no_access.html', status=403)
            if permission and not getattr(request.membership, permission):
                return HttpResponseForbidden('Você não tem permissão para esta operação.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def context(request, page, **extra):
    return {'tenant': request.tenant, 'membership': request.membership, 'page': page, **extra}


@require_GET
def home(request):
    return redirect('novainfo:dashboard' if request.user.is_authenticated else 'novainfo:login')


@tenant_required()
@require_GET
def dashboard(request):
    return render(request, 'tenant/dashboard.html', context(request, 'home',
        grants=AccessGrant.objects.filter(tenant=request.tenant).order_by('-created_at')[:8],
        created_today=AccessGrant.objects.filter(tenant=request.tenant, status='active', created_at__date=timezone.localdate()).count(),
    ))


@tenant_required()
@require_GET
def online(request):
    rows, error = [], ''
    try:
        rows = RouterClient(router_for(request.tenant)).online()
    except RouterUnavailable:
        error = OFFLINE
        AuditLog.objects.create(tenant=request.tenant, actor=request.user, action='router_unavailable')
    return render(request, 'tenant/users_online.html', context(request, 'online', rows=rows, error=error, checked_at=timezone.now()))


@tenant_required('can_create')
@require_http_methods(['GET', 'POST'])
def create_access(request):
    tokens = request.session.get('hotspot_requests', [])
    if request.method == 'GET':
        token = str(uuid.uuid4())
        request.session['hotspot_requests'] = (tokens + [token])[-20:]
        form = AccessForm(initial={'devices': 1, 'duration_hours': 1, 'request_id': token})
    else:
        form = AccessForm(request.POST)
        if form.is_valid():
            if str(form.cleaned_data['request_id']) not in tokens:
                form.add_error(None, 'Solicitação inválida. Reabra o formulário.')
            else:
                try:
                    grant, password = issue_access(request.tenant, request.user, form.cleaned_data)
                except RouterUnavailable as exc:
                    form.add_error(None, str(exc))
                else:
                    text = f'Wi-Fi {request.tenant.name}\nUsuário: {grant.username}\nSenha: {password}\nTempo: {grant.duration_label} de uso\nDispositivos simultâneos: {grant.devices}'
                    return render(request, 'tenant/access_created.html', context(request, 'create', grant=grant, password=password, whatsapp='https://wa.me/?' + urlencode({'text': text})))
    return render(request, 'tenant/create_user.html', context(request, 'create', form=form))


@tenant_required('can_customize')
@require_http_methods(['GET', 'POST'])
def customization(request):
    branding = Branding.objects.filter(tenant=request.tenant).first() or Branding(tenant=request.tenant)
    form = BrandingForm(request.POST or None, request.FILES or None, instance=branding)
    if request.method == 'POST' and form.is_valid():
        save_branding(request.tenant, request.user, form)
        messages.success(request, 'Hotspot atualizado. A nova imagem já está disponível na página de conexão.')
        return redirect('novainfo:customization')
    return render(request, 'tenant/customization.html', context(request, 'customize', form=form, branding=branding))


@tenant_required()
@require_http_methods(['GET', 'POST'])
def account(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        AuditLog.objects.create(tenant=request.tenant, actor=user, action='password_changed')
        messages.success(request, 'Senha alterada.')
        return redirect('novainfo:account')
    return render(request, 'tenant/account.html', context(request, 'account', form=form))


def public_tenant(request, tenant_id):
    tenant = get_object_or_404(Tenant, pk=tenant_id, active=True)
    host_tenant = getattr(request, 'hostname_tenant', None)
    if host_tenant and host_tenant.pk != tenant.pk:
        raise Http404
    return tenant


@require_GET
@never_cache
def captive(request, tenant_id):
    tenant = public_tenant(request, tenant_id)
    login_url = ''
    with tenant_scope(tenant.pk):
        branding = Branding.objects.filter(tenant=tenant).first()
        try:
            login_url = validate_login_url(router_for(tenant).login_url)
        except (RouterUnavailable, ValueError, ValidationError):
            pass
        return render(request, 'tenant/captive.html', {'public_tenant': tenant, 'branding': branding, 'login_url': login_url})


@require_GET
def wallpaper(request, tenant_id):
    tenant = public_tenant(request, tenant_id)
    with tenant_scope(tenant.pk):
        branding = get_object_or_404(Branding, tenant=tenant)
        if not branding.wallpaper:
            raise Http404
        try:
            stream = branding.wallpaper.open('rb')
        except FileNotFoundError:
            raise Http404 from None
    response = FileResponse(stream, content_type='image/webp')
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
