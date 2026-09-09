# Schema notes

The rendered, live version of this document is **`/vault/`** (it introspects the models at
request time, so it can never go stale). This file is the prose + diagram copy for the repo.

## Relationship map

```
                    ┌───────────────────────┐
                    │    core_restaurant     │  singleton: currency, tax%, service%, hours
                    └───────────┬───────────┘
                                │ (read by services for money + defaults)
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
┌───────▼────────┐   ┌──────────▼─────────┐   ┌──────────▼──────────┐
│  auth_user     │1:1│ accounts_staffprofile│  │  core_activitylog   │
│ (Django)       │───│ role, duties, perms │  │ verb·table·object_id│
└───────┬────────┘   └──────────┬─────────┘   └─────────────────────┘
        │ added_by / uploaded_by│ waiter / chef / received_by
        │                       │
┌───────▼───────────────────────▼─────────┐        ┌──────────────────────┐
│              menu_item                  │  FK    │      menu_photo      │
│ name · match_key · price · stock · par  │───────▶│ file · checksum(uniq)│
│ UNIQUE(category_id, match_key)          │ SET_NULL│ dims · bytes · tags │
│ CHECK(price >= 0)                       │        │  ▲  shared by N dishes│
└───────┬───────────────────┬─────────────┘        └────┼─────────────────┘
        │ CASCADE           │ CASCADE                   │ photo FK inherited
┌───────▼───────────┐ ┌─────▼─────────────────┐         │ by menu/signals.py
│ menu_pricechange  │ │  menu_stockmovement   │◀────────┘
│ old→new, Δ%, actor│ │ IN/OUT · balance_after│
└───────────────────┘ │ · reason · reference  │
                      └───────────────────────┘

┌────────────────┐        ┌───────────────────┐   ┌─────────────────┐
│  orders_table  │◀── SET ─│    orders_order    │──▶│ accounts_staff  │
│ x,y,rotation   │  NULL  │ number · status ·  │   │ profile (waiter,│
│ (3D floor map) │        │ channel · totals   │   │  chef)          │
└────────────────┘        └─────────┬─────────┘   └─────────────────┘
                                    │ CASCADE
                      ┌─────────────▼─────────────┐   ┌──────────────────┐
                      │       orders_orderline     │──▶│    menu_item     │
                      │ quantity · unit_price(snap)│   │ (SET NULL keeps  │
                      │ course · state · notes     │   │  the line alive) │
                      └────────────────────────────┘   └──────────────────┘
   orders_payment (order FK, method, amount, tip)  ·  orders_guestnote (1:1, rating)
```

## Column-level decisions

| Table | Column | Why |
| --- | --- | --- |
| `menu_item` | `match_key` | Normalised name, `db_index`, part of the uniqueness constraint. It is *the* hook for twin detection, photo inheritance and the "restock instead of duplicate" flow. |
| `menu_item` | `photo_source`, `photo_note` | Records *why* a dish has its image (`upload`, `library`, `inherited`) so the UI can say "re-used from X" instead of pretending it's magic. |
| `menu_item` | `par_level`, `low_stock_threshold` | Two numbers, not one: par drives "fill to par (+N)", threshold drives the amber state. Both per-dish, with the venue default as the fallback. |
| `menu_item` | `sold_total`, `last_sold_at` | Denormalised, written by the ledger, indexed (`idx_dish_last_sold`) — the dashboard's "turns/day" never has to scan movements. |
| `menu_photo` | `checksum` UNIQUE | sha-1 of the bytes. Two identical uploads become one file and two links; the browser hashes too, so the admin is told *before* uploading. |
| `menu_stockmovement` | `balance_after` | The ledger is self-verifying: sum the movements and you can rebuild stock during an audit. |
| `orders_order` | `subtotal/service/tax/total` | Stored at close time, computed by `recompute()` with the venue's percentages — reports don't re-derive money on read. |
| `orders_orderline` | `name_at_order`, `unit_price` | Snapshots. Rename or reprice a dish and yesterday's ticket still prints what the guest actually saw and paid. |
| `orders_table` | `x`, `y`, `rotation` | The 3D floor map is driven by real geometry, not a hard-coded layout. |
| everything | `created_at`, `updated_at` | One abstract `TimeStampedModel`; `get_latest_by` gives `.latest()` for free. |

## Indexes and constraints that matter

```sql
-- generated from the models; visible live at /vault/
CREATE UNIQUE INDEX menu_item_pkey                        ON menu_item (id);
CREATE UNIQUE CONSTRAINT uniq_dish_per_chapter            ON menu_item (category_id, match_key);
CREATE CHECK       price_not_negative                     ON menu_item (price >= 0);
CREATE INDEX       idx_dish_chapter_avail                 ON menu_item (category_id, is_available);
CREATE INDEX       idx_dish_price                         ON menu_item (price DESC);
CREATE INDEX       idx_dish_last_sold                    ON menu_item (last_sold_at DESC);
CREATE UNIQUE      menu_photo.checksum                    ON menu_photo (checksum);
CREATE INDEX       idx_price_item_time                   ON menu_pricechange (item_id, created_at DESC);
CREATE INDEX       idx_stock_item_time                   ON menu_stockmovement (item_id, created_at DESC);
CREATE INDEX       idx_stock_dir_reason                  ON menu_stockmovement (direction, reason);
CREATE INDEX       idx_order_status_time                 ON orders_order (status, created_at DESC);
CREATE INDEX       idx_order_channel_state               ON orders_order (channel, status);
CREATE INDEX       idx_table_zone_state                  ON orders_table (zone, status);
CREATE INDEX       idx_activity_target                   ON core_activitylog (table, object_id);
CREATE INDEX       idx_staff_role_duty                   ON accounts_staffprofile (role, is_on_duty);
```

SQLite runs with `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL` (set in
`config/settings.py`, printed by `/api/vault/`) so the `PROTECT`/`SET_NULL` behaviour is enforced
by the database, not only by the ORM.

## Data flow, end to end

1. **Guest** taps a plate on `/menu/` → `POST /api/guest/order/` → `Order` (channel `web`,
   status `new`) + `OrderLine`s; each line immediately `consume()`s stock, writing an
   `OUT` movement referencing the ticket number. The dashboard's next poll shows it on the rail.
2. **Waiter** fires the ticket (`advance`) → `FIRE`; every line goes to `cooking`, the table's
   state becomes `running`, the floor map lifts that table and its ring turns hot.
3. **Chef** marks lines ready → `READY` → `SERVED`; the lane timer (`kitchen_lane_minutes`)
   decides when a ticket turns red.
4. **Cashier** settles → `Payment` row, `total` frozen, table `clearing`, stock already drained.
5. Every step writes `core_activitylog`, which *is* the dashboard's activity feed.
6. **Manager** reprices or restocks in `/studio/` → `menu_pricechange` / `menu_stockmovement`,
   the composer's badges update, and if a photo is touched the `post_save` signal pushes it to
   every twin before the response is even rendered.
