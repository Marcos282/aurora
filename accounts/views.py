import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import LoginAttempt


class PortalLoginView(LoginView):
    template_name = "accounts/login.html"

    def post(self, request, *args, **kwargs):
        address = request.META.get("REMOTE_ADDR", "")
        key = hmac.new(settings.SECRET_KEY.encode(), address.encode(), hashlib.sha256).hexdigest()
        now = timezone.now()
        with transaction.atomic():
            attempt, _ = LoginAttempt.objects.get_or_create(key=key, defaults={"window_start": now})
            attempt = LoginAttempt.objects.select_for_update().get(pk=attempt.pk)
            if attempt.window_start < now - timedelta(minutes=15):
                attempt.failures = 0
                attempt.window_start = now
            if attempt.failures >= 10:
                return render(request, self.template_name, {"form": self.get_form(), "throttled": True}, status=429)
            attempt.failures += 1
            attempt.save()
        response = super().post(request, *args, **kwargs)
        if response.status_code == 302:
            LoginAttempt.objects.filter(key=key).update(failures=0)
        return response


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("panel")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if request.POST.get("terms") != "yes":
            form.add_error(None, "Confirme os termos e a maioridade para criar a conta.")
        else:
            form.save()
            return redirect("login")
    return render(request, "accounts/register.html", {"form": form})
