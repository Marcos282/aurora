from django.db import models

from anunciantes.models import Advertiser


class DailyViews(models.Model):
    advertiser = models.ForeignKey(Advertiser, on_delete=models.CASCADE, related_name="daily_views")
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["advertiser", "day"], name="one_daily_view_counter")]
