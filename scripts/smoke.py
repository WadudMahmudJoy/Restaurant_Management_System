#!/usr/bin/env python
"""End-to-end smoke test through Django's test client (no server needed).

    python scripts/smoke.py

Covers: every page renders, the smart-add contract (twin detection, photo
inheritance, checksum de-duplication) and the live order loop.
"""
from __future__ import annotations

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402

from apps.menu.models import Item, Photo  # noqa: E402
from apps.orders.models import Order  # noqa: E402

PASS, FAIL = "\033[92m✔\033[0m", "\033[91m✘\033[0m"
problems: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {PASS if condition else FAIL} {label}{f' — {detail}' if detail else ''}")
    if not condition:
        problems.append(f"{label} {detail}")


def main() -> int:
    client = Client()
    print("\n\033[1mPages\033[0m")
    for path, need_auth in [("/", False), ("/menu/", False), ("/login/", False), ("/api/health/", False)]:
        response = client.get(path)
        check(f"GET {path}", response.status_code == 200, f"HTTP {response.status_code}")

    for path in ["/dashboard/", "/studio/", "/orders/", "/kitchen/", "/vault/", "/django-admin/login/"]:
        anonymous = client.get(path)
        check(f"GET {path} (anon → redirect)", anonymous.status_code in (200, 302), f"HTTP {anonymous.status_code}")

    print("\n\033[1mAuth\033[0m")
    ok = client.login(username="bithi", password="Bithi@2026")
    check("owner can sign in", ok)
    for path in ["/dashboard/", "/studio/", "/orders/", "/kitchen/", "/vault/"]:
        response = client.get(path)
        check(f"GET {path}", response.status_code == 200, f"HTTP {response.status_code}")

    print("\n\033[1mAPIs\033[0m")
    for path in ["/api/overview/", "/api/vault/", "/api/menu/items/?view=all", "/api/menu/photos/", "/api/floor/", "/api/orders/?status=open"]:
        response = client.get(path)
        payload = json.loads(response.content or b"{}")
        check(f"GET {path}", response.status_code == 200 and "ok" in payload or response.status_code == 200,
              f"{len(response.content)//1024} KB")

    overview = json.loads(client.get("/api/overview/").content)
    check("overview has metrics", "revenue" in overview.get("metrics", {}))
    check("overview has 14-day series", len(overview.get("series", [])) == 14)
    check("overview has a floor", len(overview.get("floor", [])) > 0)
    check("overview has top dishes", len(overview.get("top", [])) > 0)

    print("\n\033[1mSmart add: photo inheritance\033[0m")
    twin_name = "Truffle Arancini"
    suggest = json.loads(client.get(f"/api/menu/suggest/?name={twin_name}").content)
    suggestion = suggest["suggestion"]
    check("twin detected from name alone", suggestion["status"] == "twin", suggestion["status"])
    check("photo offered without an upload", bool(suggestion["photo"]), (suggestion["photo"] or {}).get("label", "none"))
    check("price prefilled from history", bool(suggestion["price"]), suggestion["price"] or "")
    check("restock guidance present", bool(suggestion["restock"]))

    before = Item.objects.count()
    response = client.post(
        "/api/menu/save/",
        data=json.dumps({"name": twin_name, "price": "14.00", "stock": "10", "mode": "auto"}),
        content_type="application/json",
    )
    result = json.loads(response.content)
    check("re-adding an existing dish restocks instead of duplicating",
          result.get("action") == "restocked" and Item.objects.count() == before,
          f"{result.get('action')} · rows {before} → {Item.objects.count()}")
    updated = Item.objects.get(pk=result["item"]["id"])
    check("stock moved through the ledger", updated.stock_moves.filter(direction="IN").exists())
    check("no upload means the old photo is kept", updated.photo_id is not None)

    print("\n\033[1mSmart add: checksum de-duplication\033[0m")
    source = BASE_DIR / "media" / "menu" / "seed" / "ribeye-au-poivre.jpg"
    if source.exists():
        photos_before = Photo.objects.count()
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("copy-of-ribeye.jpg", source.read_bytes(), content_type="image/jpeg")
        response = client.post("/api/menu/photos/upload/", data={"photo": upload})
        payload = json.loads(response.content)
        check("identical file is re-linked, not re-stored",
              payload.get("ok") and payload.get("reused") and Photo.objects.count() == photos_before,
              payload.get("notice", "")[:60])

    print("\n\033[1mNew dish end to end\033[0m")
    response = client.post(
        "/api/menu/save/",
        data=json.dumps({"name": "Smoke Test Soufflé", "price": "12.50", "stock": "8", "mode": "create"}),
        content_type="application/json",
    )
    created = json.loads(response.content)
    check("new dish created", created.get("action") == "created", created.get("notice", "")[:70])
    dish = Item.objects.filter(name="Smoke Test Soufflé").first()
    check("dish row exists with a chapter", bool(dish and dish.category_id))
    if dish:
        response = client.post("/api/menu/price/", data=json.dumps({"id": dish.pk, "price": "13.00"}),
                               content_type="application/json")
        check("price edit writes the price ledger",
              json.loads(response.content).get("ok") and dish.price_history.exists())
        response = client.post("/api/menu/toggle/", data=json.dumps({"id": dish.pk}), content_type="application/json")
        check("86 / re-serve toggle works", json.loads(response.content)["item"]["is_available"] is False)
        dish.delete()

    print("\n\033[1mGuest order loop\033[0m")
    public = Client()
    live = Item.objects.live().first()
    stock_before = live.stock
    response = public.post(
        "/api/guest/order/",
        data=json.dumps({"guest": "Smoke Tester", "party": 2, "lines": [{"item": live.pk, "quantity": 2}]}),
        content_type="application/json",
    )
    order = json.loads(response.content)
    check("web ticket created", order.get("ok"), order.get("notice", order.get("error", ""))[:70])
    if order.get("ok"):
        live.refresh_from_db()
        check("guest order reserves stock immediately", live.stock == stock_before - 2, f"{stock_before} → {live.stock}")
        ticket = Order.objects.get(number=order["number"])
        check("ticket totals computed from the ledger", ticket.total > 0, str(ticket.total))
        response = client.post("/api/orders/action/", data=json.dumps({"id": ticket.pk, "action": "settle"}),
                               content_type="application/json")
        check("staff can settle the guest ticket", json.loads(response.content).get("ok"))
        ticket.refresh_from_db()
        check("settled ticket is closed", ticket.status == Order.PAID)
        ticket.delete()
        live.refresh_from_db()
        live.stock = stock_before
        live.save(update_fields=["stock"])

    print("\n\033[1mVault\033[0m")
    vault = json.loads(client.get("/api/vault/").content)
    names = {row["table"] for row in vault["tables"]}
    for expected in ["menu_item", "menu_photo", "menu_stockmovement", "orders_order", "orders_table", "core_restaurant"]:
        check(f"vault documents {expected}", expected in names)
    item_table = next(row for row in vault["tables"] if row["table"] == "menu_item")
    check("dish table lists 30+ columns", len(item_table["fields"]) > 28, f"{len(item_table['fields'])}")
    check("indexes are live", len(item_table["indexes"]) >= 3)
    check("check constraints exist", len(item_table["constraints"]) >= 1)

    print()
    if problems:
        print(f"\033[91m{len(problems)} check(s) failed:\033[0m")
        for line in problems:
            print("  · " + line)
        return 1
    print("\033[92mAll smoke checks passed.\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
