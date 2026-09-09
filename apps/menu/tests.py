"""Menu tests: the smart-add contract, ledgers and the photo library."""
from __future__ import annotations

import io
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Category, Item, Photo, PriceChange, StockMovement, normalize


class SmartAddTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="Passw0rd!", is_staff=True)
        cls.starter = Category.objects.create(name="Small Plates", service_order=10)
        cls.grill = Category.objects.create(name="Wood Grill", service_order=20)
        cls.blob = b"\xff\xd8\xff\xe0fakejpegbytes"
        cls.photo = Photo.objects.create(
            file=SimpleUploadedFile("arancini.jpg", cls.blob, content_type="image/jpeg"),
            label="Truffle Arancini", checksum=Photo.fingerprint(io.BytesIO(cls.blob)), source="seed",
        )
        cls.arancini = Item.objects.create(
            name="Truffle Arancini", category=cls.starter, price=Decimal("14.00"),
            stock=12, par_level=30, photo=cls.photo, added_by=cls.owner,
        )

    def test_normalise_is_stable_and_stopword_free(self):
        self.assertEqual(normalize("  The Truffle Arancini!! "), "truffle arancini")
        self.assertEqual(normalize("Classic Cacio e Pepe"), "cacio pepe")

    def test_twin_is_detected_from_a_name_alone(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("menu:api_suggest"), {"name": "Truffle Arancini"})
        suggestion = response.json()["suggestion"]
        self.assertEqual(suggestion["status"], "twin")
        self.assertEqual(suggestion["photo"]["id"], self.photo.pk)
        self.assertEqual(Decimal(suggestion["price"]), self.arancini.price)
        self.assertEqual(suggestion["restock"]["needed"], 18)

    def test_re_adding_restocks_instead_of_duplicating(self):
        self.client.force_login(self.owner)
        before = Item.objects.count()
        response = self.client.post(
            reverse("menu:api_save"),
            data={"name": "Truffle Arancini", "price": "14.00", "stock": "10", "mode": "auto"},
        )
        payload = response.json()
        self.assertEqual(payload["action"], "restocked")
        self.assertEqual(Item.objects.count(), before)
        self.arancini.refresh_from_db()
        self.assertEqual(self.arancini.stock, 22)
        self.assertEqual(self.arancini.photo_id, self.photo.pk)
        self.assertTrue(StockMovement.objects.filter(item=self.arancini, direction="IN", quantity=10).exists())

    def test_price_change_is_ledgered(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("menu:api_price"), data={"id": self.arancini.pk, "price": "16.50"})
        self.arancini.refresh_from_db()
        self.assertEqual(self.arancini.price, Decimal("16.50"))
        change = PriceChange.objects.latest("created_at")
        self.assertEqual((change.old_price, change.new_price), (Decimal("14.00"), Decimal("16.50")))
        self.assertEqual(change.delta_pct, 18)

    def test_new_dish_gets_photo_from_a_sibling_match(self):
        """A near-twin in another chapter borrows the existing photo automatically."""
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("menu:api_save"),
            data={"name": "Truffle Arancini", "category": self.grill.pk, "price": "15.00", "stock": "6", "mode": "create"},
        )
        payload = response.json()
        self.assertTrue(payload["ok"])
        created = Item.objects.get(pk=payload["item"]["id"])
        self.assertEqual(created.photo_id, self.photo.pk)
        self.assertIn(created.photo_source, ("library", "inherited"))

    def test_identical_upload_is_relinked_not_restored(self):
        self.client.force_login(self.owner)
        payload = self.blob
        before = Photo.objects.count()
        response = self.client.post(
            reverse("menu:api_photo_upload"),
            {"photo": SimpleUploadedFile("the-same-picture.jpg", payload, content_type="image/jpeg")},
        )
        body = response.json()
        self.assertTrue(body["ok"])
        # checksum match only happens for genuinely identical bytes; the fixture
        # file is tiny but real, so the library must not grow.
        self.assertEqual(Photo.objects.count(), before)
        self.assertTrue(body["reused"])

    def test_photo_added_later_propagates_to_twins(self):
        twin = Item.objects.create(name="truffle arancini ", category=self.grill, price=Decimal("15.00"))
        self.assertIsNone(twin.photo_id)
        other = Photo.objects.create(
            file=SimpleUploadedFile("second.jpg", b"\xff\xd8\xff\xe0otherbytes", content_type="image/jpeg"),
            label="Second angle", checksum="def456",
        )
        self.arancini.photo = other
        self.arancini.save()
        twin.refresh_from_db()
        self.assertEqual(twin.photo_id, other.pk)
        self.assertEqual(twin.photo_source, "inherited")

    def test_dish_is_unique_per_chapter(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Item.objects.create(name="Truffle Arancini", category=self.starter, price=Decimal("14.00"))

    def test_sixty_nine_and_restock_helpers(self):
        item = Item.objects.create(name="Soup", category=self.starter, price=Decimal("8.00"),
                                    stock=4, par_level=20, low_stock_threshold=6)
        self.assertEqual(item.stock_state, "low")
        self.assertEqual(item.needs_restock, 16)
        item.eighty_six(actor=self.owner)
        item.refresh_from_db()
        self.assertFalse(item.is_available)
        self.assertEqual(item.stock_state, "out")  # 86'd beats the stock number
        item.is_available = True
        item.save()
        item.restock(20, actor=self.owner)
        item.refresh_from_db()
        self.assertEqual(item.stock, 24)
        self.assertEqual(item.stock_state, "ample")


class GuestFacingTests(TestCase):
    def setUp(self):
        self.starter = Category.objects.create(name="Small Plates")
        self.item = Item.objects.create(name="Soup", category=self.starter, price=Decimal("8.00"), stock=3)

    def test_public_menu_page_renders(self):
        response = self.client.get(reverse("menu:guest"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "plated")

    def test_sold_out_dish_is_hidden(self):
        self.item.stock = 0
        self.item.save()
        response = self.client.get(reverse("menu:guest"))
        self.assertNotIn("Soup", response.content.decode())
