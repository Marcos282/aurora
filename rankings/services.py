from django.db.models import F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from anunciantes.models import Advertiser
from assinaturas.models import Subscription


def public_advertisers():
    now = timezone.now()
    current = Subscription.objects.filter(
        advertiser_id=OuterRef("pk"), starts_at__lte=now, ends_at__gt=now, revoked=False,
    ).order_by("-priority", "-ends_at")
    return Advertiser.objects.filter(
        active=True, status="approved", approved_revision=F("revision"),
        identity__status="verified",
    ).annotate(
        sponsored_priority=Coalesce(Subquery(current.values("priority")[:1]), Value(0), output_field=IntegerField()),
        active_tier=Coalesce(Subquery(current.values("tier")[:1]), Value("basic")),
    ).prefetch_related("photos").order_by("-sponsored_priority", "-updated_at", "pk")
