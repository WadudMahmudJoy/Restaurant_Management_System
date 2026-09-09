"""Platform tests: money formatting, the journal, analytics and the login rails."""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from apps.menu.models import Category, Item
from apps.orders.models import Order, Table

from .analytics import category_mix, floor_state, hourly_today, overview, revenue_series
from .models import ActivityLog, Restaurant
from .templatetags.rms_extras import initials, money as money_filter, signed


class VenueTests(TestCase):
    def setUp(self):
        # the venue row is deliberately cached; keep tests hermetic
        cache.clear()

    def test_singleton_is_reused_and_cached(self):
        first = Restaurant.load()
        second = Restaurant.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Restaurant.objects.count(), 1)

    def test_money_formats_with_symbol_and_thousands(self):
        venue = Restaurant.load()
        venue.currency_symbol = "$"
        self.assertEqual(venue.money(Decimal("1234.5")), "$1,234.50")
        self.assertEqual(venue.money(Decimal("-12")), "−$12.00")
        self.assertEqual(venue.money(0), "$0.00")

    def test_saving_a_venue_busts_the_cache(self):
        venue = Restaurant.load()
        venue.name = "New Name"
        venue.save()
        self.assertEqual(Restaurant.load().name, "New Name")

    def test_hours_label_and_open_flag_are_derived(self):
        venue = Restaurant.load()
        venue.is_open_override = True
        venue.save()
        self.assertTrue(venue.is_open_now)
        self.assertIn("–", venue.hours_label)


class TemplateFilterTests(TestCase):
    def test_money_filter(self):
        self.assertEqual(money_filter("12.5"), "$12.50")
        self.assertEqual(money_filter(1234.567, "€"), "€1,234.57")
        self.assertEqual(money_filter(None), "$0.00")

    def test_signed_and_initials(self):
        self.assertEqual(signed(4), "+4")
        self.assertEqual(signed(-4), "-4")
        self.assertEqual(initials("Noor Alam"), "NA")
        self.assertEqual(initials("bithi"), "BI")


class JournalTests(TestCase):
    def test_record_writes_and_truncates(self):
        row = ActivityLog.record("x" * 400, verb="updated")
        self.assertEqual(len(row.message), 220)
        self.assertIn("updated", str(row))

    def test_record_never_raises_on_bad_input(self):
        self.assertIsNone(ActivityLog.record("boom", actor=object(), obj=object()))


class AnalyticsTests(TestCase):
    def setUp(self):
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("boss", password="Passw0rd!", is_staff=True)
        cls.chapter = Category.objects.create(name="Grill", accent="#123456")
        cls.item = Item.objects.create(name="Steak", category=cls.chapter, price=Decimal("30.00"), stock=10)
        cls.table = Table.objects.create(label="T-02", seats=4)

    def make_paid_ticket(self, quantity=2):
        from django.utils import timezone

        order = Order.objects.create(guest_name="Paid", table=self.table, status=Order.PAID,
                                     paid_at=timezone.now())
        order.lines.create(item=self.item, name_at_order=self.item.name, quantity=quantity,
                           unit_price=self.item.price)
        order.recompute()
        return order

    def test_series_is_14_days_of_shape(self):
        series = revenue_series(14)
        self.assertEqual(len(series), 14)
        self.assertTrue(all({"date", "revenue", "tickets"} <= set(row) for row in series))

    def test_hourly_covers_service_window(self):
        self.assertEqual(len(hourly_today()), 13)

    def test_overview_reports_the_ticket(self):
        self.make_paid_ticket()
        data = overview()
        self.assertGreaterEqual(data["metrics"]["revenue"], 0)
        self.assertEqual(data["metrics"]["dishes"], 1)
        self.assertIn("floor", data)
        self.assertIn("series", data)

    def test_category_mix_counts_revenue(self):
        self.make_paid_ticket(2)
        mix = category_mix(14)
        self.assertEqual(mix[0]["name"], "Grill")
        self.assertAlmostEqual(mix[0]["revenue"], 60.0, places=2)

    def test_floor_state_marks_a_live_ticket(self):
        from django.utils import timezone

        order = Order.objects.create(guest_name="Live", table=self.table, status=Order.NEW,
                                     created_at=timezone.now())
        row = next(item for item in floor_state() if item["label"] == "T-02")
        self.assertEqual(row["order"]["id"], order.pk)
        self.assertTrue(row["order"]["late"] is False or row["order"]["late"] is True)


class LoginRailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("floor", password="Passw0rd!", is_staff=True)

    def test_staff_land_on_the_dashboard(self):
        response = self.client.post("/login/", {"username": "floor", "password": "Passw0rd!",
                                                "next": "/dashboard/"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Service, at a glance.")

    def test_non_staff_are_rejected_with_a_message(self):
        User.objects.create_user("guesty", password="Passw0rd!")
        response = self.client.post("/login/", {"username": "guesty", "password": "Passw0rd!"})
        self.assertContains(response, "team members")

    def test_profile_is_created_for_every_user(self):
        from apps.accounts.models import StaffProfile

        self.assertTrue(StaffProfile.objects.filter(user=self.user).exists())
        profile = self.user.profile
        self.assertTrue(profile.can_manage_menu)
        self.assertEqual(profile.initials, "FL")

    def test_anonymous_dashboard_redirects(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_logout_returns_home(self):
        self.client.force_login(self.user)
        response = self.client.post("/logout/")
        self.assertRedirects(response, "/")
