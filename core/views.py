from django.core.paginator import Paginator
from django.db.models import F
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from anunciantes.models import STATES
from estatisticas.models import DailyViews
from galerias.models import Photo
from rankings.services import public_advertisers


@require_http_methods(["GET", "POST"])
def age_gate(request):
    if request.method == "POST":
        if request.POST.get("adult") == "yes":
            request.session["adult_confirmed"] = True
            return redirect("home")
        return render(request, "core/age.html", {"error": True}, status=400)
    return render(request, "core/age.html")


@require_GET
def home(request):
    profiles = public_advertisers()
    for field in ("state", "city", "neighborhood"):
        value = request.GET.get(field, "").strip()[:80]
        if value:
            profiles = profiles.filter(**{field + "__iexact": value})
    if request.GET.get("name"):
        profiles = profiles.filter(name__icontains=request.GET["name"][:80])
    for parameter, lookup in (("min_age", "age__gte"), ("max_age", "age__lte")):
        value = request.GET.get(parameter, "")
        if value.isdigit() and 18 <= int(value) <= 100:
            profiles = profiles.filter(**{lookup: int(value)})
    if request.GET.get("featured") == "1":
        profiles = profiles.filter(sponsored_priority__gt=0)
    page = Paginator(profiles, 12).get_page(request.GET.get("page"))
    return render(request, "core/home.html", {"page_obj": page, "states": STATES})


@require_GET
def profile(request, slug):
    advertiser = get_object_or_404(public_advertisers(), slug=slug)
    seen = list(request.session.get("seen_profiles", []))
    if advertiser.pk not in seen:
        counter, _ = DailyViews.objects.get_or_create(advertiser=advertiser, day=timezone.localdate())
        DailyViews.objects.filter(pk=counter.pk).update(count=F("count") + 1)
        request.session["seen_profiles"] = (seen + [advertiser.pk])[-100:]
    return render(request, "core/profile.html", {"advertiser": advertiser, "photos": advertiser.photos.filter(approved=True)})


@require_GET
def photo_file(request, photo_id):
    photo = get_object_or_404(Photo.objects.select_related("advertiser"), pk=photo_id)
    owner = request.user.is_authenticated and (request.user.is_staff or photo.advertiser.user_id == request.user.pk)
    if not owner and (not photo.approved or not public_advertisers().filter(pk=photo.advertiser_id).exists()):
        raise Http404
    try:
        stream = photo.image.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Foto indisponivel.") from exc
    response = FileResponse(stream, content_type="image/webp")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def legal(request, page):
    return render(request, "core/legal.html", {"page": page})


@require_GET
def robots(request):
    return HttpResponse(
        "User-agent: *\nDisallow: /painel/\nDisallow: /admin/\nDisallow: /documentos/\nDisallow: /conta/\n",
        content_type="text/plain",
    )
