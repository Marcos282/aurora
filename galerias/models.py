from django.db import models

from anunciantes.models import Advertiser


class Photo(models.Model):
    advertiser = models.ForeignKey(Advertiser, on_delete=models.CASCADE, related_name="photos")
    image = models.FileField(max_length=300)
    order = models.PositiveSmallIntegerField(default=0)
    consent = models.BooleanField(default=False)
    consent_at = models.DateTimeField()
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"Foto {self.pk} - {self.advertiser}"
