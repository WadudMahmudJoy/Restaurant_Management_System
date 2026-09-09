"""
seed_demo — build a realistic, beautiful install in one command.

    python manage.py seed_demo            # idempotent: re-running refreshes demo data
    python manage.py seed_demo --flush    # wipe demo rows first

It writes real relational data (photos → dishes → ledger → tickets → payments)
so every screen has something honest to show, including 14 days of revenue.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.core.models import ActivityLog, Restaurant
from apps.menu.models import Category, Item, Photo, PriceChange, StockMovement, normalize
from apps.orders.models import GuestNote, Order, OrderLine, Payment, Table

CENT = Decimal("0.01")

VENUE = {
    "name": "Lumière",
    "tagline": "Fire, salt & patience — an open-hearth room for twelve tables.",
    "accent": "#D8B26A",
    "accent_soft": "#F0DCB0",
    "currency_symbol": "$",
    "currency_code": "USD",
    "tax_percent": Decimal("7.50"),
    "service_percent": Decimal("10.00"),
    "address": "14 Harbor Lane, Riverside District",
    "phone": "+1 202 555 0142",
    "email": "hello@lumiere.dining",
    "opens_at": datetime.strptime("11:30", "%H:%M").time(),
    "closes_at": datetime.strptime("23:30", "%H:%M").time(),
    "days_open": [0, 1, 2, 3, 4, 5, 6],
    "kitchen_lane_minutes": 16,
    "low_stock_default": 6,
    "receipt_footer": "Thank you — see you tomorrow. Chef's note: ask for the day-boat fish.",
}

CHAPTERS = [
    ("Small Plates", "Snacks to open the appetite — fork-forward, one bite each.", "#C9A227", "✦", 10),
    ("Wood Grill", "Live fire, smoke and 400°C cast iron.", "#D97757", "♨", 20),
    ("Pasta & Rice", "Hand-rolled daily, rested 24 hours.", "#9BC1BC", "❋", 30),
    ("Curry House", "Slow pots, aged 12 hours, finished à la minute.", "#E0A458", "◉", 40),
    ("Sweets", "Patisserie counter, all butter, no shortcuts.", "#D8A0B0", "✧", 50),
    ("Barista & Cold", "Single origin, filtered water at 93°C.", "#7FA1C3", "❄", 60),
    ("Sides", "The things people order twice.", "#A3B18A", "✿", 70),
    # The counter exists to prove the photo library: these are the same dishes at
    # a different price, and they inherit their twin's photograph automatically.
    ("Chef's Counter", "Two-bite formats of the à-la-carte classics, plated at the pass.", "#B9A4FF", "◈", 80),
]

# name, chapter, price, cost, stock, par, photo, prep, kcal, flags
DISHES = [
    ("Truffle Arancini", "Small Plates", "14.00", "4.10", 22, 30, "truffle-arancini", 12, 420,
     {"is_veg": True, "is_signature": True, "subtitle": "Roman rice, pecorino snow, black truffle",
      "description": "Carnaroli risotto rolled with fontina, chilled overnight, crumbed twice and fried at 180°C. Shaved truffle over at the pass.",
      "allergens": ["dairy", "gluten"], "tags": ["vegetarian", "shareable"], "pairs_with": ["Coconut Matcha"]}),
    ("Charred Octopus", "Small Plates", "19.50", "8.20", 14, 20, "", 18, 310,
     {"subtitle": "Ember-kissed, gigante beans, burnt lemon", "is_signature": False,
      "description": "Braised four hours in cork and wine, then grilled hard over binchotan. Bean purée, salsa verde, burnt lemon.",
      "allergens": ["shellfish"], "tags": ["gluten-free", "sharing"], "pairs_with": ["Single Origin Pour Over"]}),
    ("Smoked Brisket Bao", "Small Plates", "16.00", "5.75", 9, 24, "", 10, 480,
     {"subtitle": "12-hour smoke, pickled cucumber, hoiso",
      "description": "Packhouse brisket smoked low, steamed in milk buns, cucumber quick-pickle, hoisin sesame.",
      "allergens": ["gluten", "soy"], "heat": 1, "tags": ["smoky"], "pairs_with": ["Coconut Matcha"]}),
    ("Ribeye au Poivre", "Wood Grill", "46.00", "21.00", 11, 16, "ribeye-au-poivre", 22, 890,
     {"is_signature": True, "subtitle": "45-day dry aged, green peppercorn, bone marrow butter",
      "description": "Two fingers of dry-aged ribeye, charcoal seared, rested eight minutes. Cognac and green peppercorn pan sauce, marrow butter.",
      "allergens": ["dairy", "alcohol"], "tags": ["signature", "date night"], "prep_minutes": 22,
      "pairs_with": ["Truffle Parmesan Fries"]}),
    ("Miso Glazed Cod", "Wood Grill", "34.00", "14.30", 8, 14, "miso-glazed-cod", 18, 520,
     {"subtitle": "Saikyo marinade 72 hours, charred leek",
      "description": "Black cod in white miso and mirin for three days, lacquered over coals until the edges catch. Leek ash, pickled cucumber.",
      "allergens": ["fish", "soy"], "is_signature": True, "tags": ["gluten-free"],
      "pairs_with": ["Wild Mushroom Risotto"]}),
    ("Lamb Rogan Josh", "Wood Grill", "38.00", "15.10", 6, 15, "", 26, 710,
     {"subtitle": "Kashmiri chilli, ratan jot, slow shoulder",
      "description": "Shoulder braised four hours in yoghurt, Kashmiri chilli and whole spice. Finished with dry ginger and fennel pollen.",
      "allergens": ["dairy"], "heat": 2, "tags": ["slow food"], "pairs_with": ["Garlic Butter Naan"]}),
    ("Cacio e Pepe", "Pasta & Rice", "22.00", "4.90", 26, 40, "cacio-e-pepe", 11, 620,
     {"is_veg": True, "subtitle": "Tonnarelli, pecorino romano, tellicherry pepper",
      "description": "Three ingredients, no cream, no mercy. Emulsified in the pan with starchy water and aged pecorino.",
      "allergens": ["dairy", "gluten"], "tags": ["vegetarian", "classic"], "pairs_with": ["Truffle Arancini"]}),
    ("Wild Mushroom Risotto", "Pasta & Rice", "24.50", "6.80", 18, 30, "wild-mushroom-risotto", 24, 560,
     {"is_veg": True, "subtitle": "Porcini, chanterelle, aged parmesan, truffle oil",
      "description": "Carnaroli toasted in duck fat… well, brown butter. Mixed mushrooms, three-cheese finish, chive oil.",
      "allergens": ["dairy"], "tags": ["vegetarian", "comfort"], "pairs_with": ["Miso Glazed Cod"]}),
    ("Saffron Seafood Risotto", "Pasta & Rice", "31.00", "13.40", 5, 18, "", 26, 610,
     {"subtitle": "Mussels, prawns, squid, saffron threads",
      "description": "Fished-to-order seafood folded through saffron rice with a shellfish bisque reduction.",
      "allergens": ["shellfish", "fish"], "tags": ["special"], "pairs_with": ["Coconut Matcha"]}),
    ("Chicken Tikka Handi", "Curry House", "26.00", "8.90", 20, 32, "chicken-tikka-handi", 20, 640,
     {"subtitle": "Yoghurt marinade, clay oven, butter finish",
      "description": "Thigh meat marinated 24 hours, blistered in the tandoor, then simmered in handi with tomato, ginger and fenugreek.",
      "allergens": ["dairy"], "heat": 2, "tags": ["tandoor", "gluten-free"], "pairs_with": ["Garlic Butter Naan"]}),
    ("Lamb Rogan Josh Handi", "Curry House", "30.00", "12.20", 0, 18, "", 30, 720,
     {"subtitle": "The house pot — order before it goes",
      "description": "Slow lamb shoulder in Kashmiri chilli, yoghurt and dry aromatics. Sold until the pot is empty.",
      "allergens": ["dairy"], "heat": 3, "tags": ["limited"], "pairs_with": ["Basmati & Saffron"]}),
    ("Basmati & Saffron", "Curry House", "7.50", "1.40", 45, 70, "", 12, 250,
     {"is_veg": True, "subtitle": "Aged 24 months, saffron, cardamom",
      "description": "Steamed, not boiled. Each grain separate.", "allergens": [], "tags": ["side", "vegan"],
      "is_vegan": True}),
    ("Pistachio Rose Cake", "Sweets", "13.00", "3.60", 12, 18, "pistachio-rose-cake", 8, 430,
     {"is_veg": True, "is_signature": True, "subtitle": "Sicilian pistachio, rose water, raspberry gel",
      "description": "Six layers, rested overnight, mirror glaze poured at 32°C.",
      "allergens": ["egg", "dairy", "nuts", "gluten"], "tags": ["vegetarian"]}),
    ("Valrhona Chocolate Fondant", "Sweets", "14.50", "4.10", 7, 20, "valrhona-chocolate-fondant", 14, 520,
     {"is_veg": True, "subtitle": "Molten centre, gold leaf, vanilla quenelle",
      "description": "Baked to order — 11 minutes exactly. Guanaja 70%, butter from Normandy.",
      "allergens": ["egg", "dairy", "gluten"], "tags": ["baked to order"], "pairs_with": ["Single Origin Pour Over"]}),
    ("Salted Honey Tart", "Sweets", "11.00", "2.80", 3, 16, "", 6, 380,
     {"is_veg": True, "subtitle": "Buckwheat pastry, wildflower honey, flake salt",
      "description": "Blind-baked pastry, set honey custard, buckwheat crumble.",
      "allergens": ["gluten", "dairy", "egg"], "tags": ["vegetarian"]}),
    ("Single Origin Pour Over", "Barista & Cold", "6.50", "1.10", 60, 90, "single-origin-pour-over", 4, 5,
     {"subtitle": "Ethiopia Guji, washed, 15g / 250ml", "is_vegan": True, "is_veg": True,
      "description": "Ground to order, 93°C, three pours, 2:45 total brew.",
      "allergens": [], "tags": ["coffee"]}),
    ("Coconut Matcha", "Barista & Cold", "7.00", "1.60", 38, 60, "coconut-matcha-latte", 3, 180,
     {"is_vegan": True, "is_veg": True, "subtitle": "Ceremonial grade, unsweetened coconut",
      "description": "Whisked at 70°C, poured over hand-cut ice spheres.", "allergens": [], "tags": ["cold"]}),
    ("Yuzu Sparkling Soda", "Barista & Cold", "5.50", "1.05", 52, 70, "", 2, 90,
     {"is_vegan": True, "is_veg": True, "subtitle": "House yuzu cordial, soda, shiso",
      "description": "Cordial made weekly with Japanese yuzu and cane sugar.", "allergens": [], "tags": ["zero proof"]}),
    ("Truffle Parmesan Fries", "Sides", "9.50", "2.10", 30, 48, "truffle-parmesan-fries", 9, 540,
     {"is_veg": True, "subtitle": "Triple cooked, truffle salt, aged parmesan",
      "description": "Soaked, blanched, chilled, fried twice. Tossed in truffle salt with shaved 30-month parmesan.",
      "allergens": ["dairy"], "tags": ["shareable", "vegetarian"]}),
    ("Truffle Arancini", "Chef's Counter", "9.00", "2.60", 18, 24, "", 8, 280,
     {"is_veg": True, "subtitle": "Two bites, tasting format — same arancini, one fewer",
      "description": "The à-la-carte arancini, plated as a single course for the counter. Same photo, same recipe, different chapter.",
      "allergens": ["dairy", "gluten"], "tags": ["tasting"]}),
    ("Pistachio Rose Cake", "Chef's Counter", "7.50", "2.00", 10, 16, "", 5, 260,
     {"is_veg": True, "subtitle": "Half a slice, espresso on the house",
      "description": "The counter version of the signature cake. Inherited its photograph the moment it was saved.",
      "allergens": ["egg", "dairy", "nuts", "gluten"], "tags": ["tasting"]}),
    ("Garlic Butter Naan", "Sides", "5.00", "0.90", 40, 60, "", 6, 300,
     {"is_veg": True, "subtitle": "Tandoor-blistered, cultured garlic butter",
      "description": "Stretched by hand, slapped on the wall of the oven, brushed with browned garlic butter.",
      "allergens": ["gluten", "dairy"], "tags": ["vegetarian"]}),
]

TEAM = [
    ("bithi", "Bithi Rahman", "owner", "Bithi@2026", "#D8B26A", "Pass"),
    ("noor", "Noor Alam", "manager", "Noor@2026", "#9BC1BC", "Floor"),
    ("chef", "Marco Silva", "chef", "Chef@2026", "#E07A5F", "Grill"),
    ("amira", "Amira Haque", "sous", "Amira@2026", "#E0A458", "Sauté"),
    ("theo", "Theo Marchetti", "waiter", "Theo@2026", "#7FA1C3", "Main room"),
    ("ines", "Inés Duarte", "waiter", "Ines@2026", "#C6A15B", "Terrace"),
    ("ken", "Ken Watanabe", "barista", "Ken@2026", "#A3B18A", "Bar"),
]

STATIONS_BY_CHAPTER = {
    "Small Plates": "garde", "Wood Grill": "grill", "Pasta & Rice": "saute", "Curry House": "tandoor",
    "Sweets": "pastry", "Barista & Cold": "bar", "Sides": "saute", "Chef's Counter": "garde",
}

FLOOR = [
    ("T-01", 2, "main", -4.2, 3.0), ("T-02", 2, "main", -4.2, 0.6),
    ("T-03", 4, "main", -1.2, 3.0), ("T-04", 4, "main", -1.2, 0.4),
    ("T-05", 4, "main", 1.8, 3.0), ("T-06", 6, "main", 1.8, 0.2),
    ("B-01", 2, "bar", 4.6, 2.4), ("B-02", 2, "bar", 4.6, 0.4),
    ("P-01", 8, "private", -1.0, -2.6), ("P-02", 4, "private", 2.6, -2.6),
    ("R-01", 2, "terrace", -4.4, -2.4), ("R-02", 4, "terrace", -1.4, -2.4),
    ("R-03", 4, "terrace", 1.6, -2.4), ("R-04", 6, "terrace", 4.6, -2.4),
]

GUESTS = ["Élodie", "Marcus", "Priya", "Daniel", "Sofia", "Yusuf", "Clara", "Tomás",
          "Hana", "Ivan", "Beatriz", "Owen", "Amelie", "Rohan", "Greta", "Nadia"]


class Command(BaseCommand):
    help = "Populate the database with a full, realistic Lumière install."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete existing demo rows first.")
        parser.add_argument("--rebuild-tickets", action="store_true",
                            help="Regenerate the 14 days of tickets even when history exists.")
        parser.add_argument("--seed", type=int, default=20260909)

    def handle(self, *args, **options):
        random.seed(options["seed"])
        self.rebuild_tickets = options["rebuild_tickets"] or options["flush"]
        if options["flush"]:
            self.stdout.write("flushing demo rows…")
            for model in (GuestNote, Payment, OrderLine, Order, Table, StockMovement, PriceChange,
                          Item, Photo, Category, StaffProfile, ActivityLog):
                model.objects.all().delete()
        with transaction.atomic():
            venue = self._venue()
            team = self._team()
            chapters = self._chapters()
            photos = self._photos()
            items = self._dishes(chapters, photos, venue, team)
            tables = self._tables()
            self._inherit_photos()
            if self.rebuild_tickets or not Order.objects.exists():
                self._tickets(items, team, tables, venue)
                self._live_board(items, team, tables, venue)
            else:
                self.stdout.write("  tickets already present — kept (use --rebuild-tickets to regenerate)")
        self.stdout.write(self.style.SUCCESS("✔ Database seeded — see the summary below."))
        self._summary()

    # ── pieces ───────────────────────────────────────────────────────────
    def _venue(self) -> Restaurant:
        venue, _ = Restaurant.objects.get_or_create(pk=1)
        for key, value in VENUE.items():
            setattr(venue, key, value)
        venue.save()
        return venue

    def _chapters(self) -> dict[str, Category]:
        out: dict[str, Category] = {}
        for name, blurb, accent, icon, order in CHAPTERS:
            chapter, _ = Category.objects.update_or_create(
                name=name, defaults={"blurb": blurb, "accent": accent, "icon": icon,
                                     "service_order": order, "is_active": True}
            )
            out[name] = chapter
        return out

    def _photos(self) -> dict[str, Photo]:
        out: dict[str, Photo] = {}
        from django.conf import settings

        for name, chapter, price, cost, stock, par, photo, prep, kcal, extras in DISHES:
            if not photo or photo in out:
                continue
            path = settings.BASE_DIR / "media" / "menu" / "seed" / f"{photo}.jpg"
            if not path.exists():
                self.stdout.write(self.style.WARNING(f"  ! missing artwork: {path.name}"))
                continue
            with path.open("rb") as handle:
                record, reused = Photo.find_or_create(
                    file=File(handle, name=path.name), label=name, source="seed",
                    tags=[name.lower(), chapter.lower().split()[0], "plating"],
                )
            out[photo] = record
        return out

    def _dishes(self, chapters, photos, venue, team=None) -> dict[str, Item]:
        owner = team.get("bithi").user if team else None
        out: dict[str, Item] = {}
        for name, chapter, price, cost, stock, par, photo, prep, kcal, extras in DISHES:
            station = STATIONS_BY_CHAPTER.get(chapter, "saute")
            record = Item.objects.filter(category=chapters[chapter], match_key=normalize(name)).first()
            payload = {
                "name": name,
                "category": chapters[chapter],
                "price": Decimal(price),
                "cost": Decimal(cost),
                "compare_price": (Decimal(price) * Decimal("1.15")).quantize(CENT) if extras.get("offer") else None,
                "par_level": par,
                "low_stock_threshold": max(4, int(par * 0.18)),
                "prep_minutes": prep,
                "calories": kcal,
                "protein_g": max(6, int(kcal / 28)),
                "station": station,
                "photo": photos.get(photo) if photo else None,
                "photo_source": "library" if photo and photos.get(photo) else "none",
                "photo_note": "Studio artwork, plated for launch" if photo else "No photo yet — upload once, twins inherit it",
                "is_available": stock > 0,
                "added_by": owner,
                "sold_total": random.randint(4, 90),
                **{k: v for k, v in extras.items() if k not in {"offer"}},
            }
            if record:
                for key, value in payload.items():
                    setattr(record, key, value)
                record.save()
            else:
                record = Item.objects.create(**payload)
            record.stock = stock
            record.save(update_fields=["stock", "updated_at"])
            if stock:
                StockMovement.objects.get_or_create(
                    item=record, direction="IN", quantity=stock, reason="seed",
                    balance_after=stock, note="opening balance",
                )
            PriceChange.objects.get_or_create(
                item=record, old_price=Decimal("0.00"), new_price=record.price, reason="launch price"
            )
            out[name] = record
        return out

    def _inherit_photos(self) -> int:
        """Mirror the production signal: a twin with no photo borrows one by match_key."""
        inherited = 0
        for orphan in Item.objects.filter(photo__isnull=True):
            donor = (Item.objects.filter(match_key=orphan.match_key, photo__isnull=False)
                     .exclude(pk=orphan.pk).select_related("photo", "category").first())
            if donor is None:
                continue
            orphan.photo = donor.photo
            orphan.photo_source = "inherited"
            orphan.photo_note = f"Auto-shared from “{donor.name}” ({donor.category.name})"
            orphan.save(update_fields=["photo", "photo_source", "photo_note", "updated_at"])
            inherited += 1
        if inherited:
            self.stdout.write(f"  photo library inherited {inherited} twin dish(es) with no upload")
        return inherited

    def _team(self) -> dict[str, StaffProfile]:
        out: dict[str, StaffProfile] = {}
        for index, (username, full, role, password, accent, station) in enumerate(TEAM):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@lumiere.dining",
                    "first_name": full.split()[0],
                    "last_name": " ".join(full.split()[1:]),
                    "is_staff": True,
                },
            )
            if created:
                user.set_password(password)
                user.is_superuser = role == "owner"
                user.save()
            profile = user.profile
            profile.role = role
            profile.display_name = full
            profile.accent = accent
            profile.station = station
            profile.phone = f"+1 202 555 0{150 + index}"
            profile.pin = f"{2110 + index}"
            profile.is_on_duty = index < 5
            if profile.is_on_duty:
                profile.clocked_in_at = timezone.now() - timedelta(hours=random.randint(2, 6))
            profile.save()
            out[username] = profile
        return out

    def _tables(self) -> dict[str, Table]:
        out: dict[str, Table] = {}
        for label, seats, zone, x, y in FLOOR:
            table, _ = Table.objects.update_or_create(
                label=label,
                defaults={"seats": seats, "zone": zone, "x": Decimal(str(x)), "y": Decimal(str(y)),
                          "rotation": random.choice([0, 15, 345, 90]), "status": "free", "is_active": True},
            )
            out[label] = table
        return out

    def _tickets(self, items, team, tables, venue) -> int:
        """14 days of paid history so charts and top-sellers are real."""
        dish_list = list(items.values())
        waiters = [team["theo"], team["ines"], team["noor"]]
        chefs = [team["chef"], team["amira"]]
        created = 0
        for day in range(13, -1, -1):
            base = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=day)
            volume = random.randint(11, 26) + (7 if base.weekday() >= 4 else 0)
            for step in range(volume):
                opened = base + timedelta(minutes=random.randint(0, 600), seconds=random.randint(0, 59))
                status_roll = random.random()
                if status_roll < 0.06:
                    continue  # a few cancelled nights
                order = Order.objects.create(
                    status=Order.PAID, channel=random.choices(
                        ["dinein", "takeaway", "delivery", "pickup", "web"], weights=[62, 16, 10, 7, 5]
                    )[0],
                    guest_name=random.choice(GUESTS), party_size=random.randint(1, 6),
                    waiter=random.choice(waiters), chef=random.choice(chefs),
                    table=random.choice(list(tables.values())) if random.random() > 0.25 else None,
                    note=random.choice(["", "", "window side please", "nut allergy — please flag", "birthday, candle"]),
                    created_at=opened, updated_at=opened,
                    fired_at=opened + timedelta(minutes=2), ready_at=opened + timedelta(minutes=17),
                    served_at=opened + timedelta(minutes=21),
                    paid_at=opened + timedelta(minutes=random.randint(42, 88)),
                    priority=random.choices(["normal", "vip"], weights=[88, 12])[0],
                )
                picks = random.choices(dish_list, k=random.randint(2, 4))
                seen: dict[int, OrderLine] = {}
                for position, dish in enumerate(picks):
                    if dish.pk in seen:
                        seen[dish.pk].quantity += 1
                        seen[dish.pk].save(update_fields=["quantity"])
                        continue
                    line = OrderLine.objects.create(
                        order=order, item=dish, name_at_order=dish.name, quantity=1,
                        unit_price=dish.price, state="served", course=1 if position == 0 else 2,
                        position=position, fired_at=opened + timedelta(minutes=2),
                        ready_at=opened + timedelta(minutes=random.randint(9, 22)),
                        created_at=opened, updated_at=opened,
                    )
                    seen[dish.pk] = line
                order.save()  # number
                order.recompute()
                order.save(update_fields=["subtotal", "tax_total", "service_total", "total", "updated_at"])
                Payment.objects.create(
                    order=order, method=random.choices(["card", "qr", "cash", "split"], weights=[55, 25, 15, 5])[0],
                    amount=order.total, tip=(order.subtotal * Decimal(random.choice(["0", "0.05", "0.1", "0.15"]))).quantize(CENT),
                    reference="".join(random.choices("ABCDEFGH0123456789", k=10)),
                    received_by=random.choice(waiters), created_at=order.paid_at, updated_at=order.paid_at,
                )
                if random.random() < 0.35:
                    GuestNote.objects.create(
                        order=order, rating=random.choices([3, 4, 5], weights=[5, 25, 70])[0],
                        message=random.choice(["best ribeye in the city", "service was flawless", "would come back for the risotto alone",
                                                "a little slow at the start, worth it", "the bao is dangerous"]),
                    )
                for line in order.lines.select_related("item"):
                    StockMovement.objects.create(
                        item=line.item, direction="OUT", quantity=line.quantity,
                        balance_after=max(0, line.item.stock), reason="sale", reference=order.number,
                        created_at=order.paid_at, updated_at=order.paid_at,
                    )
                created += 1
        return created

    def _live_board(self, items, team, tables, venue):
        """A handful of tickets currently on the rail, in every state."""
        dish_list = [dish for dish in items.values() if dish.is_available]
        live = [
            (Order.NEW, 6, "theo", 4),
            (Order.FIRE, 22, "ines", 3),
            (Order.FIRE, 9, "noor", 2),
            (Order.READY, 4, "theo", 5),
            (Order.SERVED, 35, "ines", 2),
        ]
        seats = ["T-03", "T-01", "B-01", "T-05", "R-02"]
        for index, (status, age_minutes, waiter_key, covers) in enumerate(live):
            opened = timezone.now() - timedelta(minutes=age_minutes)
            order = Order.objects.create(
                status=status, channel="dinein", guest_name=random.choice(GUESTS), party_size=covers,
                waiter=team[waiter_key], chef=team["chef"], created_at=opened, updated_at=opened,
                note=random.choice(["", "allergy: shellfish", "celebrating an anniversary", "splits the bill"]),
                priority="rush" if status == Order.FIRE and age_minutes > 18 else "normal",
            )
            for position, dish in enumerate(random.sample(dish_list, k=random.randint(2, 4))):
                OrderLine.objects.create(
                    order=order, item=dish, name_at_order=dish.name, quantity=random.randint(1, 3),
                    unit_price=dish.price, course=position + 1, position=position,
                    state={"new": "queued", "fire": "cooking", "ready": "ready", "served": "served"}[status],
                    notes=random.choice(["", "", "no onion", "extra sauce on the side", "well done"]),
                    created_at=opened, updated_at=opened,
                )
            order.save()
            order.recompute()
            order.save(update_fields=["subtotal", "tax_total", "service_total", "total", "updated_at"])
            table = tables.get(seats[index])
            if table:
                table.status = {"new": "seated", "fire": "running", "ready": "dessert", "served": "settling"}[status]
                table.save(update_fields=["status", "updated_at"])
        ActivityLog.record("Demo install seeded — menu, ledger, floor and 14 days of tickets",
                           verb="created", level="good", table="core_restaurant")

    def _summary(self):
        rows = [
            ("dishes on the menu", Item.objects.count()),
            ("chapters", Category.objects.count()),
            ("photos in the library", Photo.objects.count()),
            ("dishes sharing a photo", Photo.objects.exclude(items__isnull=True).values("id")
             .annotate(uses=Count("items", distinct=True)).filter(uses__gt=1).count()),
            ("dishes with no photo", Item.objects.filter(photo__isnull=True).count()),
            ("team members", StaffProfile.objects.count()),
            ("tables on the floor", Table.objects.count()),
            ("tickets (all states)", Order.objects.count()),
            ("ticket lines", OrderLine.objects.count()),
            ("stock ledger rows", StockMovement.objects.count()),
            ("price ledger rows", PriceChange.objects.count()),
            ("activity log rows", ActivityLog.objects.count()),
        ]
        width = max(len(label) for label, _ in rows)
        for label, count in rows:
            self.stdout.write(f"  {label.ljust(width)}  {count:>6}")
        self.stdout.write("\n  sign in at /login/ with  bithi / Bithi@2026   (owner · full access)")
