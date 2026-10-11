import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

STATES = [
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapa"), ("AM", "Amazonas"),
    ("BA", "Bahia"), ("CE", "Ceara"), ("DF", "Distrito Federal"), ("ES", "Espirito Santo"),
    ("GO", "Goias"), ("MA", "Maranhao"), ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"),
    ("MG", "Minas Gerais"), ("PA", "Para"), ("PB", "Paraiba"), ("PR", "Parana"),
    ("PE", "Pernambuco"), ("PI", "Piaui"), ("RJ", "Rio de Janeiro"), ("RN", "Rio Grande do Norte"),
    ("RS", "Rio Grande do Sul"), ("RO", "Rondonia"), ("RR", "Roraima"), ("SC", "Santa Catarina"),
    ("SP", "Sao Paulo"), ("SE", "Sergipe"), ("TO", "Tocantins"),
]


class Advertiser(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        PENDING = "pending", "Aguardando moderacao"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Reprovado"
        SUSPENDED = "suspended", "Suspenso"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="advertiser")
    name = models.CharField("nome publico", max_length=80)
    slug = models.SlugField(unique=True, max_length=120, editable=False)
    age = models.PositiveSmallIntegerField("idade declarada", validators=[MinValueValidator(18), MaxValueValidator(100)])
    state = models.CharField("estado", max_length=2, choices=STATES)
    city = models.CharField("cidade", max_length=80)
    neighborhood = models.CharField("bairro", max_length=80, blank=True)
    summary = models.CharField("resumo", max_length=180)
    description = models.TextField("descricao", max_length=5000)
    contact = models.CharField("contato autorizado", max_length=100, blank=True)
    contact_consent = models.BooleanField(default=False)
    available = models.BooleanField("disponivel", default=False)
    active = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=1)
    approved_revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["state", "city", "status", "active"])]
        constraints = [models.CheckConstraint(condition=models.Q(age__gte=18, age__lte=100), name="advertiser_adult_age")]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = (slugify(self.name) or "perfil")[:85] + "-" + uuid.uuid4().hex[:12]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("profile", args=[self.slug])
