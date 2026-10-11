import hashlib
import hmac
import json
import tempfile
import time
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from anunciantes.models import Advertiser
from assinaturas.models import Plan, Subscription
from galerias.models import Photo
from galerias.services import store_photo
from moderacao.models import IdentityCheck
from moderacao.services import adult_on, approve, store_identity
from pagamentos.models import Payment
from pagamentos.services import reconcile
from rankings.services import public_advertisers


class PortalTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = override_settings(MEDIA_ROOT=Path(self.temp.name) / "media", PRIVATE_ROOT=Path(self.temp.name) / "private")
        override.enable()
        self.addCleanup(override.disable)
        self.user = get_user_model().objects.create_user("test_advertiser", password="OnlyTest123!")
        self.other = get_user_model().objects.create_user("other_test", password="OnlyTest123!")
        self.advertiser = Advertiser.objects.create(
            user=self.user, name="Perfil de teste ficticio", age=25, state="RJ", city="Cidade de Teste",
            summary="Dados exclusivamente ficticios.", description="Descricao de teste sem dados reais.", status="pending",
        )
        self.client.post(reverse("age-gate"), {"adult": "yes"})

    def png(self):
        buffer = BytesIO()
        Image.new("RGB", (32, 32), "#9944ee").save(buffer, "PNG")
        return SimpleUploadedFile("fixture.png", buffer.getvalue(), content_type="image/png")

    def verified(self):
        IdentityCheck.objects.create(advertiser=self.advertiser, encrypted_path="test.enc", status="verified", birth_date=date(1990, 1, 1), consent=True)
        photo = Photo.objects.create(advertiser=self.advertiser, image=store_photo(self.png()), approved=True, consent=True, consent_at=timezone.now())
        approve(self.advertiser, self.user)
        return photo

    def plan(self):
        return Plan.objects.create(name="Plano Teste", tier="premium", price=Decimal("100.00"), days=30, priority=10, description="Teste")

    def payment(self):
        plan = self.plan()
        return Payment.objects.create(advertiser=self.advertiser, plan=plan, amount=plan.price, days=30, tier=plan.tier, priority=plan.priority)

    def provider_data(self, payment, status="approved"):
        return {"id": 12345, "external_reference": str(payment.pk), "currency_id": "BRL", "transaction_amount": "100.00", "status": status}

    def test_age_gate_requires_confirmation(self):
        self.client.session.flush()
        self.client.cookies.clear()
        self.assertRedirects(self.client.get("/"), reverse("age-gate"))
        self.assertEqual(self.client.post(reverse("age-gate"), {}).status_code, 400)
        self.assertEqual(self.client.get(reverse("privacy")).status_code, 200)

    def test_no_profile_published_without_verification(self):
        self.assertFalse(public_advertisers().exists())
        with self.assertRaises(ValidationError):
            approve(self.advertiser, self.user)
        self.assertEqual(self.client.get(self.advertiser.get_absolute_url()).status_code, 404)

    def test_photo_section_explains_missing_profile(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("panel"))
        self.assertContains(response, 'id="minhas-fotos"', count=1)
        self.assertContains(response, "Antes de adicionar fotos")
        self.assertNotContains(response, 'name="image"')

    def test_pending_profile_can_upload_photos_before_approval(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("panel"))
        self.assertContains(response, 'id="minhas-fotos"', count=1)
        self.assertContains(response, 'name="image"')
        response = self.client.post(reverse("upload-photo"), {"image": self.png(), "consent": "yes"})
        self.assertEqual(response.status_code, 302)
        photo = self.advertiser.photos.get()
        self.assertFalse(photo.approved)
        self.assertTrue(photo.consent)
        self.assertFalse(public_advertisers().exists())

    def test_public_gallery_and_own_data_access(self):
        photo = self.verified()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertContains(self.client.get("/"), self.advertiser.name)
        self.assertEqual(self.client.get(reverse("photo-file", args=[photo.pk])).status_code, 200)
        photo.approved = False
        photo.save()
        self.assertEqual(self.client.get(reverse("photo-file", args=[photo.pk])).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse("photo-action", args=[photo.pk]), {"action": "delete"}).status_code, 404)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_profile_edits_hide_previous_approval(self):
        self.verified()
        self.client.force_login(self.user)
        response = self.client.post(reverse("panel"), {
            "name": "Novo perfil ficticio", "age": 25, "state": "RJ", "city": "Cidade de Teste",
            "summary": "Resumo de teste", "description": "<script>teste</script>",
        })
        self.assertEqual(response.status_code, 302)
        self.advertiser.refresh_from_db()
        self.assertEqual(self.advertiser.status, "pending")
        self.assertEqual(self.advertiser.revision, 2)
        self.assertFalse(public_advertisers().exists())

    def test_minor_age_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("panel"), {
            "name": "Ficticio", "age": 17, "state": "RJ", "city": "Teste",
            "summary": "Resumo", "description": "Descricao",
        })
        self.assertContains(response, "18")
        self.advertiser.refresh_from_db()
        self.assertEqual(self.advertiser.age, 25)
        self.assertFalse(adult_on(date(2010, 1, 1), date(2026, 1, 1)))
        self.assertTrue(adult_on(date(2008, 1, 1), date(2026, 1, 1)))

    def test_webp_conversion_and_invalid_upload(self):
        name = store_photo(self.png())
        from django.core.files.storage import default_storage
        with default_storage.open(name) as stream, Image.open(stream) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertFalse(image.getexif())
        with self.assertRaises(ValidationError):
            store_photo(SimpleUploadedFile("x.svg", b"<svg></svg>"))

    def test_document_encrypted_and_permission_restricted(self):
        key = Fernet.generate_key().decode()
        with override_settings(IDENTITY_ENCRYPTION_KEY=key):
            name = store_identity(self.png())
            payload = (Path(self.temp.name) / "private" / name).read_bytes()
            self.assertTrue(payload.startswith(b"gAAAA"))
            self.assertTrue(Fernet(key.encode()).decrypt(payload).startswith(b"RIFF"))
            identity = IdentityCheck.objects.create(advertiser=self.advertiser, encrypted_path=name, consent=True)
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(reverse("identity-document", args=[identity.pk])).status_code, 302)

    def test_disabled_payments_do_not_create_or_activate_subscription(self):
        payment = self.payment()
        self.client.force_login(self.user)
        self.client.post(reverse("checkout", args=[payment.plan_id]))
        self.assertFalse(Subscription.objects.exists())
        self.assertEqual(self.client.get(reverse("panel") + "?payment=success").status_code, 200)
        self.assertFalse(Subscription.objects.exists())
        self.assertEqual(self.client.post(reverse("payment-webhook"), json.dumps({"data": {"id": 123}}), content_type="application/json").status_code, 400)

    def test_payment_idempotency_amount_checks_refund(self):
        payment = self.payment()
        reconcile(self.provider_data(payment))
        reconcile(self.provider_data(payment))
        self.assertEqual(Subscription.objects.count(), 1)
        subscription = Subscription.objects.get()
        self.assertEqual(subscription.ends_at - subscription.starts_at, timedelta(days=30))
        data = self.provider_data(payment)
        data["transaction_amount"] = "99.00"
        with self.assertRaises(ValidationError):
            reconcile(data)
        reconcile(self.provider_data(payment, "refunded"))
        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)

    def test_expired_subscription_has_no_ranking_benefit(self):
        self.verified()
        payment = self.payment()
        reconcile(self.provider_data(payment))
        self.assertEqual(public_advertisers().get().sponsored_priority, 10)
        Subscription.objects.update(ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(public_advertisers().get().sponsored_priority, 0)

    def test_verified_webhook_and_forged_signature(self):
        payment = self.payment()
        timestamp = str(int(time.time()))
        request_id = "test-request"
        secret = "test-webhook-secret"
        digest = hmac.new(secret.encode(), f"id:12345;request-id:{request_id};ts:{timestamp};".encode(), hashlib.sha256).hexdigest()
        headers = {"HTTP_X_SIGNATURE": f"ts={timestamp},v1={digest}", "HTTP_X_REQUEST_ID": request_id}
        url = reverse("payment-webhook") + "?data.id=12345"
        with override_settings(PAYMENTS_ENABLED=True, PAYMENT_PROVIDER_APPROVED=True,
                               MERCADOPAGO_ACCESS_TOKEN="test-token", MERCADOPAGO_WEBHOOK_SECRET=secret):
            with patch("pagamentos.views.provider_request", return_value=self.provider_data(payment)):
                response = self.client.post(url, json.dumps({"data": {"id": "12345"}}), content_type="application/json", **headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.client.post(url, json.dumps({"data": {"id": "12345"}}), content_type="application/json", **headers).status_code, 200)
                headers["HTTP_X_SIGNATURE"] = f"ts={timestamp},v1=bad"
                self.assertEqual(self.client.post(url, json.dumps({"data": {"id": "12345"}}), content_type="application/json", **headers).status_code, 400)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_delete_request_immediately_hides_profile(self):
        self.verified()
        self.client.force_login(self.user)
        self.client.post(reverse("delete-account"), {"confirm": "EXCLUIR"})
        self.assertFalse(public_advertisers().exists())
        self.client.post(reverse("toggle"))
        self.assertFalse(public_advertisers().exists())

    def test_pagination_preserves_filters_and_markup_escaped(self):
        self.verified()
        self.advertiser.description = "<script>bad()</script>"
        self.advertiser.save()
        response = self.client.get(self.advertiser.get_absolute_url())
        self.assertContains(response, "&lt;script&gt;")
        self.assertEqual(self.client.get("/?city=Cidade+de+Teste&min_age=18").status_code, 200)
        self.assertEqual(self.client.get("/sitemap.xml").status_code, 200)
