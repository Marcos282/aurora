from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.contrib.sitemaps import Sitemap
from django.contrib.sitemaps.views import sitemap
from django.urls import path

from accounts.views import PortalLoginView, register
from core import views
from dashboard import views as dashboard
from moderacao import views as moderation
from pagamentos import views as payments
from rankings.services import public_advertisers


class ProfileSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return public_advertisers()

    def lastmod(self, obj):
        return obj.updated_at


urlpatterns = [
    path("", views.home, name="home"),
    path("maioridade/", views.age_gate, name="age-gate"),
    path("perfil/<slug:slug>/", views.profile, name="profile"),
    path("perfil/<slug:slug>/denunciar/", moderation.report, name="report"),
    path("fotos/<int:photo_id>/", views.photo_file, name="photo-file"),
    path("conta/entrar/", PortalLoginView.as_view(), name="login"),
    path("conta/cadastrar/", register, name="register"),
    path("conta/sair/", LogoutView.as_view(), name="logout"),
    path("painel/", dashboard.panel, name="panel"),
    path("painel/fotos/adicionar/", dashboard.upload_photo, name="upload-photo"),
    path("painel/fotos/<int:photo_id>/", dashboard.photo_action, name="photo-action"),
    path("painel/visibilidade/", dashboard.toggle, name="toggle"),
    path("painel/excluir/", dashboard.delete_account, name="delete-account"),
    path("painel/identidade/", dashboard.submit_identity, name="submit-identity"),
    path("gestao/", dashboard.admin_dashboard, name="management"),
    path("documentos/<int:pk>/", moderation.identity_document, name="identity-document"),
    path("pagamentos/checkout/<int:plan_id>/", payments.checkout, name="checkout"),
    path("pagamentos/webhook/", payments.webhook, name="payment-webhook"),
    path("termos/", views.legal, {"page": "terms"}, name="terms"),
    path("privacidade/", views.legal, {"page": "privacy"}, name="privacy"),
    path("robots.txt", views.robots),
    path("sitemap.xml", sitemap, {"sitemaps": {"profiles": ProfileSitemap}}),
    path("admin/", admin.site.urls),
]
