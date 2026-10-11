from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from anunciantes.models import Advertiser


class Plan(models.Model):
    name = models.CharField(max_length=60)
    tier = models.CharField(max_length=10, choices=[("basic", "Basico"), ("featured", "Destaque"), ("premium", "Premium")])
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(1)])
    days = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(1)])
    priority = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)
    description = models.CharField(max_length=200)

    class Meta:
        ordering = ["priority", "price"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="plan_positive_price"),
            models.CheckConstraint(condition=models.Q(days__gt=0), name="plan_positive_days"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.tier == "basic" and self.priority != 0:
            raise ValidationError({"priority": "O plano basico deve ter prioridade zero."})
        if self.tier != "basic" and self.priority < 1:
            raise ValidationError({"priority": "Publicidade exige prioridade maior que zero."})


class Subscription(models.Model):
    advertiser = models.ForeignKey(Advertiser, on_delete=models.PROTECT, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    tier = models.CharField(max_length=10)
    priority = models.PositiveSmallIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(db_index=True)
    payment = models.OneToOneField("pagamentos.Payment", on_delete=models.PROTECT)
    revoked = models.BooleanField(default=False)

    @property
    def is_active(self):
        now = timezone.now()
        return not self.revoked and self.starts_at <= now < self.ends_at
