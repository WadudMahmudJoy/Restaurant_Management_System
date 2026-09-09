# Lumière · Restaurant Management System

A 3D, single-page-feel control room for a restaurant: a WebGL landing page, a guest menu
guests can actually order from, a **menu studio** that adds a dish from three fields, a live
service board, a kitchen display and a **data vault** that documents its own schema.

Built on **Django 5.2 + SQLite + Three.js**, with zero build step: no bundler, no Node
runtime required to run the app, no CDN dependency at runtime (three.js is vendored).

```
┌──────────────┬───────────────────────────────────────────────────────────────────┐
│ Route        │ What it is                                                         │
├──────────────┼───────────────────────────────────────────────────────────────────┤
│ /            │ Landing page — WebGL turntable of plated dishes, live menu data     │
│ /menu/       │ Guest menu: 3D tilt cards, cart, orders straight into the kitchen    │
│ /dashboard/  │ Control room: KPIs, revenue curves, chapter mix, 3D floor, ledger    │
│ /studio/     │ Smart add / restock / reprice + the shared photo library             │
│ /orders/     │ Four-lane ticket board + staff ticket composer                       │
│ /kitchen/    │ Kitchen display: fire tickets, tap-a-line-to-plate                  │
│ /vault/      │ Live schema explorer: tables, columns, relations, indexes, rows     │
│ /django-admin│ The real Django admin, re-skinned, with inlines and bulk actions    │
└──────────────┴───────────────────────────────────────────────────────────────────┘
```

---

## 1. Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo        # full, realistic demo install
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

…or with the Makefile: `make setup migrate seed run`.

Sign in at `/login/` — **bithi / Bithi@2026** (owner). Other seeded roles:
`noor` (manager), `chef`, `amira` (sous), `theo`, `ines` (servers), `ken` (barista); each
password is `Name@2026` as shown on the login card.

Verify a fresh install in one line:

```bash
.venv/bin/python manage.py test        # 41 unit/integration tests
.venv/bin/python scripts/smoke.py      # 40 end-to-end checks against the dev database
```

## 2. The "smart add" — what makes this different

The admin form asks for **name, price, stock** (chapter optional). Everything else is inferred
from your own data, via `apps/menu/intelligence.py`:

| Situation | What the studio does |
| --- | --- |
| You type a dish that already exists (same normalised name) | **No duplicate row.** It offers *restock to par* + the last-known price, and the save becomes an update with a stock movement in the ledger. |
| That dish was photographed before | The photo is attached automatically, labelled *auto-inherited from "X"*. You never re-upload it. |
| You add a near-twin (same dish, new chapter, seasonal relaunch) | The closest match's photo is offered with one click; save it and every twin inherits it (a `post_save` signal propagates it). |
| You drag in a photo that is byte-identical to one already stored | Hashed in the browser with SHA-1, matched against `menu_photo.checksum`, **re-linked instead of uploaded**; the server de-dupes again on the same checksum. |
| You edit a dish | The existing photo stays. Nothing about editing requires an image again. |
| You leave price or chapter blank | Price falls back to that dish's last price → chapter median → house default; the chapter is guessed from name tokens and the dish's twin. |
| You leave stock blank | Par level from history, else the venue default × 4 — and the number is written as an opening `StockMovement`. |

Name matching is deliberately crude-but-forgiving: `normalise()` lowercases, strips punctuation,
drops stopwords and single-letter filler (`"The classic Cacio e Pepe!!"` → `cacio pepe`), and the
result is stored in `menu_item.match_key` and indexed — which is also what powers the
`UNIQUE (category_id, match_key)` guard against duplicate dishes inside one chapter.

## 3. The database

Eleven domain tables, four apps. `make docs`-style tour in **/vault/** (live, introspected).

```
core_restaurant          singleton venue: brand, currency, tax/service, hours, station targets
core_activitylog         append-only journal — the dashboard feed, filterable by table + object

accounts_staffprofile    1:1 with auth_user: role, permissions JSON, duty state, pin, accent

menu_category            chapters ("Wood Grill") with accent colour, icon and service_order
menu_photo               SHARED photo library: file, sha-1 checksum (unique), dims, tags, uploader
menu_item                a dish: name, match_key, price/cost/compare, stock/par/threshold,
                         photo FK, station, prep minutes, diet flags, allergens, tags, sold stats
menu_pricechange         price ledger (old, new, reason, actor) — powers price memory + Δ%
menu_stockmovement       stock ledger (IN/OUT/ADJUST, quantity, balance_after, reason, reference)

orders_table             the floor: label, seats, zone, x/y/rotation (the 3D map reads these)
orders_order             a ticket: number, status rail, channel, guest, table, waiter, chef,
                         subtotal/service/tax/total, timestamps for each lifecycle hop
orders_orderline          line with a PRICE SNAPSHOT (unit_price) so history never rewrites itself
orders_payment            money in, with tip; supports split payments
orders_guestnote          rating + feedback, tied 1:1 to the ticket
```

Design choices worth naming:

* **Ledgers, not mutations.** Stock and price never change silently; every change is a row
  (`menu_stockmovement`, `menu_pricechange`) with an actor and a balance snapshot.
* **Money is snapshotted** on `orders_orderline.unit_price`; editing a price can't rewrite the past.
* **Real constraints**: `UNIQUE (category_id, match_key)`, `CHECK (price >= 0)`,
  `CHECK (seats >= 1)`, `PROTECT` on `Item.category` (no orphaned dishes), `SET_NULL` on
  `Item.photo` (deleting a picture never deletes a dish), `db_index` on every hot lookup,
  three partial-free indexes for the dashboard's queries.
* **One query per panel.** `apps/core/analytics.py` aggregates with `annotate/Coalesce/TruncDate`;
  the floor map comes from a single open-orders query mapped by table, not an N+1 loop.
* SQLite runs in **WAL** with `foreign_keys=ON` and `synchronous=NORMAL` (settings.py), and
  /vault/ prints the live `PRAGMA` values so the choice is visible, not folklore.

## 4. Front end

* `static/js/scenes.js` — three.js factories: stage/renderer, three-light rig, a *procedural*
  studio environment (canvas → PMREM, so metals and glazes reflect without an HDR file),
  lathed ceramic plates, contact-shadow textures, gold dust particles and six stylized plated
  dishes (burger, ramen, pizza, ribeye, cake, matcha) built from primitives.
* `static/js/hero.js` — the landing/scene: damped pointer orbit, drag-to-rotate, intro pop-in
  with stagger, raycast hover that pins an HTML label to the real 3D position, click-to-scroll
  to the matching menu card, auto-pause off-screen, adaptive pixel-ratio when frames drop,
  and a CSS fallback when WebGL is missing.
* `static/js/floor.js` — the dashboard's 3D floor plan: extruded rounded tables, chairs,
  status rings, pulse on late tickets, hover tooltip, click → `rms:table` event → the ticket opens.
* `static/js/rms.js` — the kernel: CSRF-aware `fetch`, toasts, drawer/modal, `IntersectionObserver`
  reveals, pointer-tracked 3D tilt with glare, eased counters and dependency-free SVG charts.
* `static/css/base.css` — the tokens: ink surfaces, champagne gold, hairlines, one display serif,
  one grotesque, one mono; grain + vignette + pointer spotlight; everything respects
  `prefers-reduced-motion`.

## 5. Layout

```
config/            settings (env-driven), urls, wsgi/asgi, config/env.py
apps/core/         models (venue singleton, activity journal), analytics, views, admin skin,
                   templatetags/rms_extras.py, management/commands/seed_demo.py
apps/accounts/     StaffProfile + role defaults, signals, admin
apps/menu/         Category, Photo, Item, PriceChange, StockMovement, intelligence.py,
                   signals.py (twin photo propagation), studio views + API, decorated admin
apps/orders/       Table, Order, OrderLine, Payment, GuestNote, board/KDS views + API
templates/         base.html, public/, dashboard/, registration/, partials
static/{css,js}/   5 stylesheets, 10 JS modules, vendored three.module.js
media/menu/seed/   studio food photography committed so the demo always looks finished
scripts/smoke.py   end-to-end checks (pages, smart-add contract, order loop, vault)
docs/SCHEMA.md     the same schema, in prose + ASCII diagram
```

## 6. API (all JSON, CSRF-guarded writes)

```
GET  /api/overview/            dashboard payload (metrics, series, hourly, mix, top, stock, floor, tickets, activity)
GET  /api/vault/               live schema introspection
GET  /api/health/              venue + open-ticket counters

GET  /api/menu/items/?q=&view=&category=      view ∈ all|live|low|out|no-photo|hidden|featured
GET  /api/menu/items/<id>/                    dish + stock ledger
GET  /api/menu/suggest/?name=&category=&price=   the smart-add brain
POST /api/menu/save/            name/price/stock (+photo file, photo_id, mode=auto|restock|create)
POST /api/menu/restock/ | /adjust/ | /price/ | /toggle/ | /delete/
GET  /api/menu/photos/          POST /api/menu/photos/upload/ | /attach/ | /delete/

GET  /api/orders/?status=open|all|<state>
POST /api/orders/action/        advance | ready | settle | cancel | hold | line
POST /api/orders/create/        staff-side ticket composer
POST /api/guest/order/          public: reserves stock, creates a real ticket
GET  /api/floor/                POST /api/floor/table/
```

## 7. Notes for a real deployment

`DEBUG=False`, set `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` in the environment
(or copy `.env.example`), serve `static/` and `media/` from object storage, and move
`DATABASES` to Postgres — the models are portable (JSONField, CheckConstraints and all).
Keep the `Photo` checksum unique if you swap storage: de-duplication depends on it.
