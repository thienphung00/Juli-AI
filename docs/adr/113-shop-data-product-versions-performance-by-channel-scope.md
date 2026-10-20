# ADR-113: Shop data — product history is a chain of versions, performance is counted per product × day × channel, and the first scope adds promotions, video / live, daily inventory and reviews

- **Status:** Accepted (owner, 2026-10-20, grill D70)
- **Date:** 2026-10-20
- **Decisions:** D70.4, D70.5, D70.6 (grill D4–D6, `docs/product/data-platform/GRILL_LOG.md`)
- **Related ADRs / decisions:** [ADR-009](009-entity-centric-data-model.md) (canonical keys),
  [ADR-029](029-phase-2.9-analytics-historical-backfill.md) (A-34 backfill, call budget),
  [ADR-046](046-cdp-medallion-physical-model.md) (medallion, per-domain cutover),
  [ADR-077](077-incremental-impact-measurement.md), [ADR-101](101-tests-derive-from-captured-fixtures.md),
  [ADR-105](105-a-poll-cycle-has-a-verdict-and-leaves-a-record.md),
  [ADR-107](107-card-journey-log-and-measurement-plan.md) (amended for D70.9 / D70.11),
  [ADR-108](108-shop-diagnosis-report.md) (A-34 channel blocks), ADR-112 (ingestion platform:
  bronze, `ops` job queue, partitions, mappers — D70.1–3, 7, 8, 14, 15), ADR-115 (known-at, D70.12).
  Fast track: D25.12 / P17 (history depth), D27.3 (commerce interval), D30.1a / D30.1b / D30.4 / P23
  (product snapshots, promotions, webhook re-reads), D31.3 / P24 (ingest gateway), P8-B (video
  windows), P8-C (`run_write_values`).
- **Inputs:** `docs/product/data-platform/GAP_MAP_FASTTRACK.md`, `docs/product/data-platform/P0_TIKTOK_WEBHOOKS.md`.

## Context

The grill (D70) asks for three things about a connected shop's own data: a versioned product
history, a per-channel daily performance table that every reader and the model share, and a
first data scope beyond products and orders. Much of it exists on this branch already, built for
other reasons. This ADR says what is reused, what changes, and what is new.

**Product history today (D30.1a, P23, MIG 087).** `product_snapshots` is append-only (SELECT,
INSERT for `juli_app`), unique per `(shop_id, tiktok_product_id, snapshot_date, state_hash)`.
`services/product_history/normalize.py` hashes:
`content_hash = sha256([title, description_hash, [image URI in order], attributes_hash])` and
`state_hash = sha256([content_hash, [[sku_id, list_price, sale_price] …], status, category_id])`.
So image order, SKU set and prices, status and category are **already** in the hash (the gap map's
"hash lacks image order / category" is stale). `store.record_read` writes a snapshot when the state
changed and one `external_changes` row per changed kind, with `juli_write` set by
`store.matches_juli_write` against `run_write_values` (P8-C). Writers: the daily
`product-history-fanout` beat (03:53 UTC+7, `job.reconcile_products`: Search Products for every
status, re-read when `update_time` moved or a listed SKU price differs) and webhooks 15 / 16 / 18
(`product_history/webhooks.py` → `refresh_product`). What is missing for D4:

1. No `valid_from` / `valid_to` and no "current" read: a reader must window over `taken_at`.
2. **A same-day revert is lost.** A → B → A within one local day: the second A collides with the
   day-unique key (and `_same_day_state_exists` skips it), so the chain says B is current. This is
   exactly the seller revert D70.11 must see.
3. The row records the *detection path* (`source` = `webhook_15`, `reconcile`, `baseline` …), not
   *who* changed the product. Webhook 15 carries `change_source` (`SELLER_CENTER` | `OPEN_API`);
   nothing reads it.
4. SKU stock and SKU sales attributes / `seller_sku` are not hashed. Stock deliberately is not (see
   decision 2).
5. Change detection runs once a day. The 15-minute cycle's products step (`polling/sync.py
   sync_products`, `update_time` watermark, at most hourly by D27.3) feeds `products` only.
6. No raw Get Product body is kept (no product bronze).

**Performance today.** Three overlapping stores, none keyed the D5 way:

| Table | Migration | Shape | Gap vs D5 |
|---|---|---|---|
| `analytics_performance_intervals` | 017 / 018 / 075 | unique `(shop_id, snapshot_key)`; `grain` product / sku / shop / live / hour; stores rates (`ctr`, `click_to_order_rate`); `clicks` derived `round(impressions × ctr)`; channel only in `traffic_breakdown` / `sales_breakdown` JSON | no add-to-cart, channel not a key, rates stored, no revision time; ~30 reader modules (impact reader, `lever_flows/measurement.py`, `optimize_product/daily_funnel.py`, `product_history/baselines.py`, `analytics_kpi_precompute/*`, `aggregates/*`) |
| `shop_daily_streams` / `shop_daily_products` | 085 | PK `(shop_id, stream, day)` / `(shop_id, stream, product_id, day)`; impressions, clicks, orders, GMV | written by the diagnosis report, top 15 products per stream only; a derived (gold) table |
| `platform_daily_metrics` | 088 | unique `(shop_id, platform, dataset, day, item_id, stream, segment, order_type)`; neutral streams; has `add_to_cart`, `units`, `visitors`, `source_rank`, `confidence`, `raw_payload_id` | Shopee extension gateway only (D31.3); uuid PK, extra dimensions, rates stored |

The daily analytics pass (`polling/ingestion.py _daily_analytics`) fetches from the last
fully-fetched day + 1, so a day TikTok revises later is never re-read. Channel names are already
neutral in two places: `shop_diagnosis/channels.py` `Channel` and `ingest/mapping.py` `STREAM_*`.

**First scope today (D6).** Promotions: `promotion_activities` + `promotion_activity_products`
(D30.1b), activities of every status with per-SKU activity price — coupons are not stored. Video:
`shop_diagnosis_daily/video_windows.py` reads the date-ranged video endpoints but only into the
report's temporary snapshot folder. LIVE: `bronze.live_hours_raw_payloads` (MIG 029, A-28) and a
current-state `livestreams` table. Inventory: `inventory_items` is current-state (unique per SKU);
webhook 68 and the hourly Search Inventory step overwrite it. Reviews: nothing.

**What the API cannot give.** TikTok returns no edit history for products, no inventory history and
no review history. Everything before the shop's connect date for those three is unknowable;
performance (≈180 days, D25.12), promotions (expired activities are listed) and the video list
(post dates) do reach back.

## Decision

### 1. Product versions: migrate `product_snapshots` additively and add two views — no new table

`product_snapshots` stays the one product-history table (one writer: `store.record_read`). Next
migration after 094 (expand, `juli_app` grants unchanged):

| Column | Type | Meaning |
|---|---|---|
| `prev_snapshot_id` | uuid NULL, FK self | the version this one replaces; NULL for the first version of a product |
| `valid_from` | timestamp NULL | when the state took effect: TikTok `update_time` if it moved past the predecessor's, else `taken_at` |
| `valid_from_basis` | varchar(16) NULL | `update_time` \| `detected` (price-only changes may not move `update_time`) |
| `change_origin` | varchar(16) NULL | see decision 3 |
| `hash_version` | smallint NOT NULL DEFAULT 1 | hash recipe version (decision 2) |
| `bronze_id` | uuid NULL | the raw Get Product row in ADR-112's bronze (decision 4) |
| `mapper_version` | smallint NULL | ADR-112 / D70.8 |

New indexes: unique `(shop_id, tiktok_product_id, prev_snapshot_id)` where
`prev_snapshot_id IS NOT NULL`, and unique `(shop_id, tiktok_product_id)` where
`prev_snapshot_id IS NULL AND created_at >= <migration date>` (one first version per product from now on; older rows predate the chain). Two concurrent
writers appending after the same predecessor collide; the loser re-reads and retries. This replaces
the day-unique key as the replay guard, so A → B → A on one day stores three versions.
`uq_product_snapshots_day_state` and `_same_day_state_exists` are removed in the **deferred contract
step** that follows (operator-run, repo deferred-migration practice), after the writer sets
`prev_snapshot_id` on every new row. Existing rows are not updated (append-only table, additive gate);
the views fill their gaps.

Views (`WITH (security_invoker = true)`, so the table's RLS applies; SELECT to `juli_app`):

- `silver.product_versions` — every row of `product_snapshots` plus
  `valid_from = COALESCE(valid_from, taken_at)`,
  `valid_to = LEAD(valid_from) OVER (PARTITION BY shop_id, tiktok_product_id ORDER BY taken_at, id)`
  (NULL = current), `known_at = taken_at` (ADR-115), and
  `left_censored = (source = 'baseline')` — the state existed *at least* since `valid_from`; nothing
  before the connect date is known.
- `silver.product_current` — `DISTINCT ON (shop_id, tiktok_product_id)` latest by
  `(taken_at DESC, id DESC)`, served by the existing `ix_product_snapshots_product_taken`.

A view, not a second "current" table: one writer, consistent by construction. If the 50-shop
EXPLAIN in Verification shows `product_current` over its budget, it becomes a table written by
`record_read` in the same transaction — not before. `products` (written by the poll ETL) is
unchanged here; it moves in the products-domain cutover (ADR-112 / D70.14), when its readers are
pointed at `product_current`.

### 2. What the version hash covers

`hash_version = 2` adds to `state_hash`: each SKU's `seller_sku` and sales attributes
(`[[attr_id, value_id] …]` sorted). Unchanged: title, description hash, **image URIs in order**,
product attributes, SKU set and list / sale prices, status, leaf category.

**SKU stock is not in the hash** (grill D4 lists it). Stock moves with every order (webhook 68
fires per order); hashing it would create a version per sale and drown the content and price
changes D70.11 attributes. Stock history is its own table (decision 7) and joins by
`(shop_id, sku_id, day)`. Owner to confirm.

On the first read after the deploy, a product whose state differs only because of the new recipe
gets a snapshot with `source = 'rehash'` and **no** `external_changes` row (the field-wise `diff`
finds nothing). `record_read` compares hashes only when `hash_version` matches.

### 3. Every version records where the change came from

`change_origin` is set by `record_read` from evidence it already has:

| Value | Evidence |
|---|---|
| `juli` | `store.matches_juli_write` matched a `run_write_values` row (P8-C; that row links to `production_write_audit`) |
| `seller_center` | webhook 15 `change_source = SELLER_CENTER` for this re-read |
| `other_app` | webhook 15 `change_source = OPEN_API` and no Juli write matched |
| `platform` | webhook 5 / 37 audit or suspension, or 18 category change with no seller evidence |
| `unknown` | detected by polling, no webhook evidence (price, SKU, deactivate / delete) |
| `baseline` / `rehash` | first version at connect / recipe change |

`webhooks.py` passes `change_source` and `changed_fields` into `refresh_product` (today dropped).
The per-field split `juli` / `seller_revert` / `seller_change` and the `seller_change` card event
are ADR-107's amendment (D70.9, D70.11 (3)); they read `change_origin` and the version chain from
here.

### 4. Change detection: webhooks where TikTok has them, a 15-minute `update_time` poll and the daily reconcile for the rest

Per `P0_TIKTOK_WEBHOOKS.md`:

- **Webhook-driven re-read** (unchanged, D30.4): title / description / main images / attributes (15),
  creation (16), category (18), activity create / update / status (63 / 39). Add **5 and 37**
  (status / audit) to the `refresh_product` path. Webhooks only say "something changed"; the value
  always comes from Get Product.
- **Polled** — no webhook: price, SKU add / remove (50 has no final type id; not subscribed), seller
  deactivate / delete, coupons. New step `product_changes`: Search Products 202502 with
  `update_time_ge = cursor − 10 min`, `page_size = 100`, **every 15 minutes per shop**, rows passed
  through the existing `job._changed` filter (update_time moved or listed SKU price differs) into
  `refresh_product`. It is one call per shop per cycle in the normal case, so it runs outside the
  60-minute commerce gate of D27.3 (that gate stays for the rest of the commerce steps). Until
  ADR-112's `ops` queue lands it runs inside `run_shop_cycle`; then it is an `ops` job kind at P2
  priority. Cursor in `shop_ingestion_state` (`product_changes_cursor`), advanced only on a
  successful verdict (ADR-105).
- **Daily reconcile** (`product_history_daily`, unchanged schedule) stays the safety net: it compares
  every product's listed SKU prices, so a price change that does not move `update_time` is caught
  within a day (`valid_from_basis = 'detected'`). New: when the full listing completed without error,
  a product that was present in the previous listing and is absent now gets a version with
  `status = 'ABSENT'`, `change_origin = 'unknown'` (delete is not otherwise visible).
- **Product bronze**: every Get Product body is appended to ADR-112's `bronze.platform_raw_payloads`
  (`platform = 'tiktok'`, `endpoint = 'product.get_detail'`) before `record_read`; the snapshot keeps
  its `bronze_id`.

Open (P0, read-only on the test shop): does a Seller Center price edit fire 15 with
`changed_fields = others`, and does it move `update_time`? If yes, price leaves the "polled" row.

### 5. Performance: `silver.product_daily_performance`, keyed `(shop_id, product_id, channel, day)`

New table (next migration after 094; monthly range partitions on `day` per ADR-112 / D70.7):

| Column | Type | |
|---|---|---|
| `shop_id` | uuid | platform follows from `shops.platform` (MIG 088) |
| `product_id` | varchar(100) | platform product id (ADR-009 key within the shop) |
| `channel` | varchar(24) | CHECK in `total`, `product_card`, `shop_tab`, `seller_video`, `seller_live`, `affiliate`, `affiliate_video`, `affiliate_live` |
| `day` | date | shop-local day |
| `impressions`, `clicks`, `add_to_cart`, `orders`, `units`, `visitors` | bigint NULL | counts as the platform reports them; NULL = not reported for this channel (`shop_tab` has no add-to-cart) |
| `gmv` | numeric(18,2) NULL, `currency` varchar(10) | |
| `confidence` | varchar(16) | `high` \| `estimated` (e.g. `shop_tab` SKU orders, legacy-derived clicks) |
| `bronze_id` uuid, `mapper_version` smallint | | D70.8 |
| `first_seen_at`, `last_revised_at` | timestamp | `last_revised_at` moves only when a count changed |
| `revision_count` | smallint | |

- **Names are neutral** and are the existing ones (`shop_diagnosis/channels.py` `Channel`,
  `ingest/mapping.py` `STREAM_*`); one constant module `services/ingestion/channels.py` owns the list
  and `ADDITIVE_CHANNELS = (product_card, seller_video, seller_live, affiliate)`. `total` is stored
  as reported, never summed: `shop_tab` overlaps the others and `affiliate_video` / `affiliate_live`
  are sub-rows of `affiliate` (ADR-108 d.1). Shopee's `ads` overlay is out of scope (decision 8).
- **Counts only.** CTR, CTOR, conversion are computed at read from summed counts (ADR-108 d.1:
  never an average of daily rates). `clicks` is the channel block's own clicks field, not MIG 075's
  `round(impressions × ctr)`.
- **Keys and indexes:** PK `(shop_id, product_id, channel, day)
  INCLUDE (impressions, clicks, add_to_cart, orders, units, gmv)` — a product's series (impact
  reader, product panel) is an index-only scan; `(shop_id, day)` for whole-shop / whole-day reads;
  `BRIN (day)` per partition for fleet-wide day-range scans without a shop filter (training builder,
  daily reconcile). RLS through `app_current_shop_id()` (087 shape); `juli_app` SELECT, INSERT,
  UPDATE; no DELETE.
- **Side tables**, same conventions and partitioning:
  `silver.sku_daily_performance` PK `(shop_id, product_id, sku_id, day)` from A-32 (total only unless
  the endpoint returns channel blocks — checked in P0 depth work), and
  `silver.shop_daily_performance` PK `(shop_id, channel, day)` from A-36 plus the A-34 `total`
  roll-up, with `(shop_id, day)` covered by the PK.
- **Revisions:** a daily `ops.ingest_jobs` fetch job (`source = poll`, priority P2) re-reads the trailing 7 complete days for
  A-34 / A-32 / A-36 per shop, even when nothing new is available. The mapper upserts with
  `ON CONFLICT … DO UPDATE … WHERE (counts) IS DISTINCT FROM (excluded counts)`, bumping
  `last_revised_at` and `revision_count`; `first_seen_at` never moves. Bronze keeps every pull, so
  "what did Juli know on day X" is answerable (ADR-115).
- **Writers:** one mapper per `(platform, endpoint)` in `services/ingestion/mappers/` (ADR-112 registry `(platform, endpoint)`):
  `tiktok_a34_product.py`, `tiktok_a32_sku.py`, `tiktok_a36_shop.py`. Backfill and the daily pass both
  go through the `ops` queue (P0 = 30 days, P1 = deeper, P2 = daily re-pull; D70.2).

### 6. Reconciling the existing performance tables (ADR-046 per-domain cutover, D70.14)

| Existing | During parallel run (Fujiwa first) | At the performance-domain cutover |
|---|---|---|
| `analytics_performance_intervals` | keeps its writer and every reader; the new silver is written beside it; the daily D70.14 reconcile compares silver ↔ intervals ↔ the A-34 script file (sim-pilot 08/10 snapshot) | readers move behind one module `services/ingestion/read/performance.py` (ADR-112 flag `INGEST_SILVER_READ_PERFORMANCE`), the `grain = product / sku / shop` writer is retired, the table stays read-only for history; `grain = live` moves with decision 7, `grain = hour` (A-37) stays until its own domain |
| history older than bronze | — | one-time mapper `legacy_intervals` turns `traffic_breakdown` / `sales_breakdown` into channel rows with `confidence = 'estimated'` (clicks were derived) and `mapper_version` tagged; A-34 rows still in `bronze.ctor_performance_raw_payloads` (MIG 029) replay at `high` |
| `shop_daily_streams` / `shop_daily_products` (085) | unchanged | become derivable from silver; Ops "Mô phỏng" reads silver; the report-time writer is retired |
| `platform_daily_metrics` (088) | unchanged (Shopee extension, D31.3) | at P8 the Shopee mapper writes the three silver tables from `ingest_raw_payloads`; the table is cut over then. Its `segment` / `order_type` dimensions have no place in the D5 key — **owner decides at P8**: one order basis for silver, or a wider key |

No long-term dual write: each cutover is one PR + flag, reversible, and the old writer is removed
within the bounded window (ADR-046 §Migration).

### 7. First data scope (D70.6)

| Data | Store | Source and cadence | Before connect |
|---|---|---|---|
| Promotion timeline | **existing** `promotion_activities` + `promotion_activity_products` (D30.1b) + view `silver.promotion_timeline` (activity × SKU × [begin, end) with type, `discount_pct`, `removed_at`) | webhooks 63 / 39 + daily `sweep_promotions` (unchanged) | expired activities are listed — partial |
| Coupons (new) | `promotion_coupons`: unique `(shop_id, coupon_id)`; type, discount, threshold, product scope JSON, begin / end, status, `tiktok_update_time`, `first_seen_at`, `refreshed_at`; upserted, no DELETE | no webhook → Search Coupon List 202406 hourly per shop (filter by update time if the request supports it, else ONGOING + NOT_START list) + inside the daily sweep | as listed by the API |
| Videos | `silver.videos` PK `(shop_id, video_id)`: `posted_at`, title, duration, `first_seen_at`, `refreshed_at`; `silver.video_products` PK `(shop_id, video_id, product_id)` with `first_seen_at`, `removed_at`; `silver.video_daily_performance` PK `(shop_id, video_id, day)`: views, product impressions, product clicks, orders, units, gmv (partitioned) | the calls `shop_diagnosis_daily/video_windows.py` already makes (list 202509, batch performance 202609, `granularity = 1D`), moved into an adapter so the report and silver share them; daily, trailing 7 days re-pulled | yes, to endpoint depth |
| LIVE | `silver.live_sessions` PK `(shop_id, live_id)`: start, end, duration, title, session totals (A-28); `silver.live_session_products` where the endpoint returns products. Per-day LIVE traffic per product is the `seller_live` channel of decision 5 | A-28 daily; replays `bronze.live_hours_raw_payloads` (MIG 029); `livestreams` (public) is cut over and its writer retired | yes, to endpoint depth |
| Daily inventory | `silver.inventory_daily` PK `(shop_id, sku_id, day)`: `product_id`, `available_close`, `available_min`, `available_max`, `out_of_stock_seen`, `last_observed_at`, `observations` (partitioned) | upserted from webhook 68 `quantity_snapshot_after_change` and the hourly Search Inventory step; `inventory_items` stays the current-state table | **no** |
| Reviews | `silver.product_review_daily` PK `(shop_id, product_id, day)`: `review_count`, `star_1` … `star_5` (cumulative as of that day); average computed at read; review text deferred | daily snapshot | **no** — and the API source for the app's scopes is confirmed in P0; if none exists, this row is dropped and the owner told |

Every new table: RLS through `app_current_shop_id()`, `juli_app` with only the verbs its writer
needs, one writer module, raw payload in ADR-112's bronze with `bronze_id` + `mapper_version` on the
silver row.

### 8. Out of scope

Ads (separate scope; excluded by ADR-029) and creator / affiliate detail beyond the `affiliate`
channel counts are deferred. Market and competitor data (FastMoss, Metric.vn) stays on the research
path (`juli-sim-pilot`); it never goes through a shop adapter or into these tables.

### 9. Phasing (D70.16)

P1: decisions 1–3 and the product bronze of 4 for Fujiwa (confirm `product_history_fanout` is live in
production, DEBT P53-A). P2: `product_changes` as an `ops` job. P3: decisions 5–6 (parallel write,
reconcile, cutover). P4: decision 7. P8: Shopee mappers into the same silver tables.

## Consequences

**Positive**

- One version chain per product with validity intervals, a cheap "current" read and an origin per
  version; same-day reverts become visible, which D70.11 needs.
- Performance has one table every reader and the model share, with add-to-cart and channel as data
  rather than JSON, and late TikTok revisions are captured with their time.
- Existing work is kept: `product_snapshots`, `external_changes`, the promotion tables, the webhook
  path and the video fetch code are extended, not rebuilt.

**Negative**

- Two "current product" reads exist until the products-domain cutover (`products`, `product_current`).
- The 7-day re-pull costs ≈ 7× the daily A-34 / A-32 / A-36 calls per shop; it must fit the D70.2
  budget at 50 shops.
- Stock is outside the product hash, so "price and stock at time T" is a join of two tables.
- Content, inventory and reviews before the connect date do not exist; the model sees the baseline
  version as left-censored for the ≈180 days of performance history that precede it.
- About 30 modules read `analytics_performance_intervals`; the read cutover is the largest slice.

**Follow-ups**

- P0: Seller Center price / SKU / deactivate test on the test shop; A-32 channel blocks; review
  endpoint and scope; coupon update-time filter.
- Owner: stock out of the version hash (decision 2); `product_changes` at 15 min outside D27.3's gate
  (decision 4); Shopee `segment` / `order_type` at P8 (decision 6).
- `docs/adr/README.md` index row; ADR-046 note that 087's tables count as silver for products /
  promotions though they live in `public`.

## Alternatives considered

- **A new `product_versions` table copied from `product_snapshots`** — two writers or a migration of
  history for no gain; the chain is derivable. Rejected.
- **Physical `valid_to` updated on the predecessor** — breaks append-only (no UPDATE grant) and needs
  a two-row write per change. Rejected; computed in the view.
- **Keep current-state product only, log diffs** (grill option B) — no replayable state at a point in
  time for training (D70.12). Rejected.
- **Extend `analytics_performance_intervals`** with channel columns — keeps the uuid / `snapshot_key`
  shape that cannot be partitioned by day with a natural PK, and the stored rates. Rejected.
- **Use `platform_daily_metrics` as the silver** — eight-part key, stored rates, Shopee-gateway
  semantics (`source_rank`); decision 6 folds it in at P8 instead.
- **Store rates beside counts** — rates of sums ≠ averages of rates; readers would mix them. Rejected.
- **Pull only new days** (today) — misses TikTok's revisions of recent days. Rejected for the 7-day
  re-pull.
- **Ads, creator detail, review text, market data in the first scope** (grill D6 B / C) — deferred.

## Verification

D15 layers that apply:

1. **Mappers on real redacted fixtures (ADR-101)** for A-34 / A-32 / A-36, video, LIVE, inventory
   (68 + Search Inventory), coupons, reviews; replay: the same bronze yields the same silver.
   Channel additivity: `product_card + seller_video + seller_live + affiliate = total` on the
   Fujiwa fixture (impressions, clicks, add-to-cart, orders, GMV).
2. **Real Postgres** (CI Postgres 16; tests must not carry the `migration_heavy` marker, so they run
   at issue tier; locally they skip without `DATABASE_URL`): A → B → A on one day gives three
   versions and the right `valid_to`; two concurrent appends after one predecessor → one wins;
   `rehash` writes no change row; the 7-day upsert is idempotent and moves `last_revised_at` only on
   a changed count; monthly partitions create / attach; two-tenant RLS (ADR-089 pattern) on every new
   table **and** on both `security_invoker` views; EXPLAIN on a 50-shop seed: product series =
   index-only scan on the PK, `product_current` within budget.
3. **D70.14 daily reconcile**: silver ↔ intervals ↔ A-34 script file within the agreed tolerance for
   N consecutive days before `INGEST_SILVER_READ_PERFORMANCE` is enabled for a shop.
4. **Leakage (ADR-115)**: `known_at` / `last_revised_at` filters return only rows known before the
   cut-off.

CI tier: unit and mapper tests at issue tier; Postgres invariants at issue tier on real Postgres;
the reconcile is an `ops` job with its own verdict (ADR-105), not a CI test.
