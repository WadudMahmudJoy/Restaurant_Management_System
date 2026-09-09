"""Service-loop tests: lifecycle, money, stock drain, floor state."""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.core.models import Restaurant
from apps.menu.models import Category, Item, StockMovement

from .models import Order, OrderLine, Payment, Table

TAX = Decimal("10.00")
SERVICE = Decimal("10.00")


class OrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user("manager", password="Passw0rd!", is_staff=True)
        cls.chef = User.objects.create_user("chef", password="Passw0rd!")
        cls.category = Category.objects.create(name="Wood Grill")
        cls.steak = Item.objects.create(name="Ribeye", category=cls.category, price=Decimal("40.00"), stock=10)
        cls.fries = Item.objects.create(name="Fries", category=cls.category, price=Decimal("8.00"), stock=20)
        cls.table = Table.objects.create(label="T-01", seats=2, x=Decimal("1"), y=Decimal("2"))
        Restaurant.objects.filter(pk=1).update(tax_percent=TAX, service_percent=SERVICE)

    def setUp(self):
        # the venue row is cached per test run; make sure our knobs are used
        venue, _ = Restaurant.objects.get_or_create(pk=1)
        venue.tax_percent, venue.service_percent = TAX, SERVICE
        venue.save()

    def _order(self, *pairs):
        order = Order.objects.create(guest_name="Tester", table=self.table, party_size=2)
        for item, qty in pairs:
            order.add_item(item, qty)
        return order

    def test_number_is_assigned_on_save(self):
        order = self._order((self.steak, 1))
        self.assertRegex(order.number, r"^LM-\d{4}$")

    def test_totals_include_service_and_tax(self):
        order = self._order((self.steak, 1), (self.fries, 2))
        self.assertEqual(order.subtotal, Decimal("56.00"))
        self.assertEqual(order.service_total, Decimal("5.60"))
        self.assertEqual(order.tax_total, Decimal("5.60"))
        self.assertEqual(order.total, Decimal("67.20"))

    def test_line_prices_are_snapshots(self):
        order = self._order((self.steak, 1))
        self.steak.price = Decimal("99.00")
        self.steak.save()
        order.refresh_from_db()
        self.assertEqual(order.lines.first().unit_price, Decimal("40.00"))
        self.assertEqual(order.subtotal, Decimal("40.00"))

    def test_lifecycle_moves_through_states(self):
        order = self._order((self.steak, 1))
        self.assertEqual(order.status, Order.NEW)
        order.advance()
        self.assertEqual(order.status, Order.FIRE)
        self.assertTrue(order.lines.filter(state="cooking").exists())
        order.advance()
        self.assertEqual(order.status, Order.READY)
        order.advance()
        self.assertEqual(order.status, Order.SERVED)
        order.advance()  # serving settles
        self.assertEqual(order.status, Order.PAID)
        self.assertTrue(order.paid_at)

    def test_settling_drains_stock_and_records_payment(self):
        order = self._order((self.steak, 2), (self.fries, 1))
        order.settle(actor=self.manager)
        self.steak.refresh_from_db()
        self.fries.refresh_from_db()
        self.assertEqual(self.steak.stock, 8)
        self.assertEqual(self.fries.stock, 19)
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        movement = StockMovement.objects.filter(item=self.steak, direction="OUT").first()
        self.assertEqual(movement.reference, order.number)
        self.assertEqual(self.steak.sold_total, 2)

    def test_cancel_frees_the_table_without_touching_stock(self):
        order = self._order((self.steak, 1))
        order.advance()
        order.cancel(actor=self.manager)
        self.steak.refresh_from_db()
        self.assertEqual(self.steak.stock, 10)
        self.assertEqual(order.status, Order.CANCELLED)

    def test_guest_order_endpoint_reserves_stock(self):
        response = self.client.post(
            "/api/guest/order/",
            data='{"guest":"Web","party":2,"lines":[{"item":%d,"quantity":2}]}' % self.steak.pk,
            content_type="application/json",
        )
        body = response.json()
        self.assertTrue(body["ok"], body)
        self.steak.refresh_from_db()
        self.assertEqual(self.steak.stock, 8)

    def test_guest_order_refuses_more_than_stock(self):
        response = self.client.post(
            "/api/guest/order/",
            data='{"lines":[{"item":%d,"quantity":99}]}' % self.steak.pk,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.steak.refresh_from_db()
        self.assertEqual(self.steak.stock, 10)
        self.assertFalse(Order.objects.filter(guest_name="Web guest").exists())

    def test_api_requires_staff_for_writes(self):
        response = self.client.post("/api/orders/action/", data='{"id":1,"action":"advance"}',
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_floor_payload_shape(self):
        order = self._order((self.steak, 1))
        order.advance()
        payload = self.client.get("/api/floor/").json()["floor"]
        row = next(item for item in payload if item["label"] == "T-01")
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["order"]["id"], order.pk)

    def test_comp_line_costs_nothing_but_still_consumes(self):
        order = self._order((self.steak, 1))
        line = order.lines.first()
        line.is_comp = True
        line.save()
        order.recompute()
        self.assertEqual(order.subtotal, Decimal("0.00"))
        order.settle()
        self.steak.refresh_from_db()
        self.assertEqual(self.steak.stock, 9)


class TableTests(TestCase):
    def test_seats_must_be_positive(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(Exception):
            Table(label="T-99", seats=0).full_clean()
