# SPEC — Optimize Product, end to end (fast track)

Source of truth for this branch. Decisions are referenced as Dn (see
`DECISIONS.md`). Code references are to `backend/src/juli_backend` (`BE/`) at
the branch point `0332c405`, mapped on 2026-10-05.

## 1. Goal

For every connected shop, automatically:

1. pull its TikTok data (fast 30 days, then full history),
2. score the whole product catalog with an ML model,
3. rank products by expected gross-profit gain (revenue gain until a cost is
   entered),
4. score each product per category and recommend specific changes,
5. execute approved listing changes on the real shop,
6. measure each change at day 7 and day 14 against the stored expected
   outcome, and feed the result back into the model.

## 2. Today (branch point) — what exists

### 2.1 Connect
- `GET /v1/auth/tiktok/start` → HMAC state (600 s) → TikTok → `GET
  /v1/auth/tiktok/callback` → `services/tiktok/oauth.py:224-231` verifies state,
  exchanges code, provisions `shops` + `tiktok_credentials` (Fernet-encrypted),
  commits.
- **Nothing runs after the callback** (`oauth.py:231-237`).

### 2.2 Ingestion
- Beat `fujiwa-poll-cycle` every 15 min (`workers/celery_app.py:130-133`) polls
  **only the configured production merchant** (`shop_id=None` →
  `resolve_production_read_credential`, `workers/services/polling/orchestrate.py:782`).
- Seller shops are polled only by the manual `POST /v1/action-cards/refresh`
  (`services/action_cards/refresh.py:42-150`).
- Commerce steps: orders, products, returns, inventory — incremental by
  `update_time` watermark (`tiktok_sync_state`), 20 pages × 50 per cycle;
  400 pages on cold start.
- Analytics (`workers/services/polling/sync.py:990-1322`): always the single
  day `[yesterday, today)` (`sync.py:963-977`), re-fetched every 15 min. One
  list call + **one detail call per SKU and per product, serially**.
  Bestsellers and promotions fetched and discarded.
- Rate limiter: 10 req / 60 s per endpoint path (`sync.py:987`).

### 2.3 Data gaps that matter for the model
- Product detail (A-33) returns daily `traffic.breakdowns[]` per content type
  (`VIDEO`, `PRODUCT_CARD`, `LIVE`) with `impressions` and `ctr`. The mapper
  keeps only the first breakdown's `ctr` and **drops impressions**
  (`integrations/tiktok/mapping.py:785-792`).
- Product list (A-34) `click_order_rate` (= CVR) is stored, but
  `conversion_rate` at product grain is never written, so the impact reader's
  product-grain `impressions` / `conversion_rate` series are empty.
- `products.price` is likely NULL: the mapper ignores `price.tax_exclusive_price`
  (`mapping.py:150-159`).
- `products.category` / `category_id` effectively NULL: nothing maps
  `category_chains`.
- No history before the poll started.

### 2.4 Scoring, cards, execution, measurement (for P3–P6; summary)
- 20 rule KPIs (30-day window) → one recommendation per workflow → one card for
  the top-revenue product (`services/action_cards/subjects.py:138-151`).
- Agent run (gpt-5.4-nano) with read tools + `update_product_listing`,
  `upload_product_image`, `update_product_price`; **writes go to the sandbox
  merchant only** (`integrations/tiktok/factories.py:172-175`).
- `daily_impact_reader` 03:23 UTC: day-7 / day-14 ratio diff-in-diff vs sibling
  controls; no expected outcome stored; nothing fed back.

## 3. Target — P1 (data layer)

### 3.1 Shop bootstrap on connect (D7, D10)
- After the OAuth callback commits, enqueue `bootstrap_shop(shop_id)` on a
  **high-priority** queue. The callback must not wait on it and must not fail
  if enqueueing fails (log + leave for the scheduler to pick up).
- **Fast phase**: commerce cold start (orders, products, returns, inventory)
  plus analytics for the **last 30 days** using date-range detail calls. When
  done, run the existing scoring + card persistence for the shop (no extra
  poll), so first cards exist.
- **History phase**: enqueued on a **low-priority** queue after the fast phase.
  Walks analytics backwards in date-range chunks until TikTok returns no data
  or an out-of-range error; records the earliest date reached. Resumable,
  idempotent, rate-limited; never blocks fast-phase work for any shop.
- Bootstrap state per shop is persisted (not-started / fast-running /
  fast-done / history-running / history-done / failed + timestamps), so the
  scheduler knows which shops need bootstrapping and so latency is measurable.

### 3.2 Per-shop scheduling (D7, D9.4)
- One beat entry fans out **one task per connected shop with a usable read
  credential** (production merchant and `SELLER_CONNECT` shops alike), using
  the per-shop credential resolver (`resolve_read_credential_for_shop`).
- A shop with no completed fast phase gets `bootstrap_shop` instead of a
  normal cycle.
- Per-shop mutex: two cycles for the same shop never overlap.

### 3.3 Cadence split (D9.1)
- **Commerce** (orders, products, returns, inventory): incremental every 15 min
  (unchanged semantics, watermarks, page caps).
- **Analytics**: once a day per shop. Fetch every day from the last stored
  analytics day + 1 up to TikTok's `latest_available_date` (self-heals gaps).
  Skip if nothing new. No more re-fetching yesterday 96× a day.

### 3.4 Date-range backfill (D9.2)
- Product (A-33) and SKU (A-31) detail calls take `start_date_ge` /
  `end_date_lt` and return daily intervals: one call per product per range,
  not per day. Shop performance likewise.

### 3.5 Parallel detail calls (D9.3)
- Per-product and per-SKU detail calls run concurrently with a bounded pool,
  still honoring the per-endpoint rate limiter and the cycle wall-clock budget.

### 3.6 Mapper fixes (feeds P3/P6)
- A-33: per day, write product-grain `impressions` (sum of breakdowns), the
  per-content-type breakdown (impressions, ctr, derived clicks), total `ctr`
  and derived `clicks`; sales breakdowns (gmv, items_sold per content type).
- A-34: also write `conversion_rate` at product grain from `click_order_rate`.
- Products: `price` from `skus[0].price.tax_exclusive_price` (fallback to the
  existing fields); `category` / `category_id` from the leaf of
  `category_chains` (product detail if search lacks it).
- New columns need an Alembic migration (revision id ≤ 32 chars).

### 3.7 Latency instrumentation
- Structured log events + persisted timestamps for: connect committed, bootstrap
  enqueued, fast phase done, first card persisted, history done. Enough to
  answer "connect → first card" from data.

## 4. Target — later phases (outline; detailed when the phase starts)

- **P2 External data (optional, D22)**: FastMoss REST client (VN) for
  competitor price (D19) and market/category context; seller cost input + CSV
  (D18). Not a prerequisite for P3. The market model (D16) waits for multiple
  shops and cleaned FastMoss data.
- **P3 Model (D22)**: product-day feature table from TikTok data (channel
  impressions/CTR, add-to-cart rate, CTOR, AOV, price, stock, promotions);
  shop model (LightGBM, orders per product-day) used for **ranking only**;
  offline quality bar (D17). Expected gain per lever = ADR-106 rule estimate
  (recoverable GMV: gap to peer median × stage volume × AOV) × per-lever
  calibration (start 0.5, updated by day-14 readings). Learned uplift model
  only once enough measured changes exist.
- **P4 Cards**: top-10 ranked / ≤5 active Optimize Product cards; per-category
  scores; stored expected outcome; scoring cadence (D11); score visible before
  approval (D6).
- **P5 Execute**: real-shop write client for `update_product_listing` and
  `upload_product_image`; `update_product_price` disabled (D13).
- **P6 Measure**: product-grain impressions/CVR series; actual vs expected;
  day-7 check-in / day-14 final (D14); per-lever calibration feeding P3 (D16, D22).

## 5. Latency targets (estimates until measured)

| Segment | Target |
|---|---|
| Connect → bootstrap starts | seconds |
| Connect → first cards | ~10–20 min (Fujiwa-sized shop) |
| History backfill | hours, low priority |
| New day of analytics → updated score | same day |
| Approve → change live | ≤ 5 min + seller confirmation |
| Change → check-in / final | day 7 / day 14 (+ ≤ 24 h) |
