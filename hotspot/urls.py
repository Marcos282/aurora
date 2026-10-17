from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views

app_name = 'novainfo'
urlpatterns = [
    path('', views.home, name='home'),
    path('conta/entrar/', views.TenantLoginView.as_view(), name='login'),
    path('conta/sair/', LogoutView.as_view(), name='logout'),
    path('painel/', views.dashboard, name='dashboard'),
    path('painel/usuarios-online/', views.online, name='online'),
    path('painel/criar-acesso/', views.create_access, name='create'),
    path('painel/personalizar/', views.customization, name='customization'),
    path('painel/minha-conta/', views.account, name='account'),
    path('hotspot/<uuid:tenant_id>/', views.captive, name='captive'),
    path('hotspot/<uuid:tenant_id>/wallpaper.webp', views.wallpaper, name='wallpaper'),
]
