# ADR-117: Shopee Seller Centre files enter through the ingest gateway; KPI contracts, lever plans and forecasts are Ops tables; the public Shopee market lane gets its own tables

**Status:** Accepted (owner, 2026-11-01; grill G1–G11 2026-10-30; step 1 of the Juli Ops Shopee dashboards brief)
**Date:** 2026-11-01
**Related ADRs / decisions:** ADR-116 (client / public lanes, consent, buyer data), ADR-112
(bronze, `mapper_version`), ADR-115 (point-in-time training data), D31.3 (one ingest gateway,
`platform_daily_metrics`), D25 (Juli Ops), D61.9 (`rank` is not a model feature).
Brief: `juli-client-ops/handoff/SESSION_BRIEF_juli_ops_shopee_dashboards.md`.

## Context

The owner follows a Shopee client (Ory) in Juli Ops: products and flows, ads and promotions,
keywords and competitors, and the contract KPI simulator. Today the data is Seller Centre files
the seller exports by hand plus public search pages; when the Shopee ISV application is approved
the Open Platform API must replace the files **on the same keys, without changing a dashboard**
(G1, G11).

What the branch already has (head `3a55fd2c`, migration head 107):

- `POST /v1/ingest/{platform}/{dataset}` (`services/ingest/gateway.py`) with `source` ∈
  {extension, file, api, vendor}, `service` consent required (ADR-116 §4), payload allowlist,
  `ingest_raw_payloads` (append-only, dedup on content hash) and `platform_daily_metrics`
  (key `(shop_id, platform, dataset, day, item_id, stream, segment, order_type)`, `source_rank`
  api 3 > extension = file 2 > vendor 1).
- Four Shopee datasets (`services/ingest/mapping.py`): `traffic_overview` (day × L1 source),
  `item_by_source`, `item_performance` (day × item), `shop_traffic` (day × device). Streams:
  `product_card`, `seller_video`, `seller_live`, `affiliate`, and `ads` as a non-additive overlay.
- `products` is TikTok-shaped: `tiktok_product_id` is NOT NULL.
- The Ops console tables (083) and `ops_sim_scenarios` (scenario deltas as JSON).

What the Ory export set contains (read 2026-11-01, `~/.juli-shop-snapshots/sim-pilot/ory/
seller_center/2026-10-29/raw/`, 60 files; column names only are reproduced here):

| Export | Grain | Order types | Fits |
|---|---|---|---|
| `shop-stats` › `(đơn …)Theo nguồn lưu lượng` | day × L1 group × L2 source (e.g. Thẻ sản phẩm › Tìm kiếm / Đề xuất / Cửa hàng / Giỏ hàng …; Dịch vụ Hiển thị › ad type) | placed / confirmed / paid | `traffic_overview`, L2 as `segment` |
| `shop-stats` monthly files 11/2025–03/2026 | **month** × L1 source | three | period table (below) |
| `shop-stats` › `Đơn hàng đã đặt / Đơn đã xác nhận / Đơn Đã Thanh Toán` | day, whole shop: sales, sales excl. Shopee subsidy, orders, clicks, visits, CVR, cancelled / returned orders and sales, buyer counts (new / existing / potential), repeat rate | three | **new** `shop_overview` |
| `productoverview` | day, shop-level product funnel: product visits, page views, bounce, search clicks, likes, add-to-cart, buyers | placed + confirmed in one row | **new** `product_overview` |
| `traffic_overview_<month>` | day × device: visitors, views, stay time, bounce, new / existing, followers | none | `shop_traffic` (exists) |
| `parentskudetail` › `Sản Phẩm Hiệu Quả Tốt` | **period** (1 day … 1 month) × item × variation: 40 metrics | placed + confirmed in one row | period table, **new** `product_period` |
| `parentskudetail` › `Sản Phẩm Mới`, `Giá (không) cạnh tranh`, `Tăng trưởng / Tối ưu / Theo dõi … DVHT` | period × item: the same metrics, membership = a Shopee flag | — | **new** `platform_product_flags` |
| `discount` › `Danh sách hiệu suất` | program: name, type, run dates, status, sales / orders / units / buyers | placed + confirmed | **new** `platform_promotions` |
| `discount` › `Biểu đồ` | day × promotion type | placed + confirmed | **new** `promotion_daily` |
| Ads by campaign (G11) | not exported yet | — | dataset name reserved |
| Public search cards (Chrome, D61 T1) | keyword × sort × page × card | — | **new** public lane |

The export has **no buyer-level field** (names, phones, addresses, order lines). The `Đơn hàng`
and `Quản lý đánh giá` exports are never loaded (HĐDV 5.1).

## Decision

### 1. Files go through the gateway, on the API's keys (G2, G3)

A file loader (step 2) posts each export through `POST /v1/ingest/shopee/{dataset}` with
`source: "file"`, so consent, the allowlist, raw copy, dedup and `source_rank` apply unchanged.
A later API row (rank 3) replaces a file row (rank 2) on the same key; both raw payloads stay.

- **`mapper_version`** (new `SMALLINT NULL` on `platform_daily_metrics` and every new
  client-lane table): the version of the server mapping that produced the row (ADR-112's
  known-at). NULL = written before this ADR. Bumped whenever `mapping.py` changes a field's
  meaning, so a file-vs-API reconciliation can tell a mapping change from a data change.
- **L2 sources are `segment` values of `traffic_overview`** (no new stream, G3). The L1 total row
  keeps `segment = 'all'`; readers sum streams over `segment = 'all'` only, so a child segment is
  never added to a total. The Shopee label → code table lives in `mapping.py` (step 2); an
  unknown label is refused (422 + drift report), never filed under `other`. Initial codes
  (≤ 16 chars): product card `search`, `recommend`, `shop_page` (Cửa hàng = KPI flow "Trang
  shop", G3), `cart`, `my_orders`, `promo`, `chat`, `other`; live / video `live_tab`,
  `live_home`, `video_tab`, `video_home`; affiliate `aff_live`, `aff_video`; ads
  `ads_roas_custom`, `ads_auto_bid`, `ads_shop`, `ads_gmvmax_shop`, `other`.
- Live / video `impressions` hold **views** (Lượt xem Livestream / Video), and ads rows hold
  **ad impressions**; the stream decides the meaning, and a CTR is never compared across
  streams. Ads revenue counts **placed** orders whatever sheet it came from (Shopee Uni 26972);
  the loader stores the sheet's order type in the key and `ads_attribution = "placed"` in `extra`.
- New daily datasets in the existing registry: `shop_overview` (stream `total`, item `''`),
  `product_overview` (stream `total`, item `''`), `promotion_daily` (stream `promo`, segment =
  promotion type code). Placed and confirmed values in one export row are posted as two posts,
  one per `order_type`.

### 2. Period totals get their own table, not a fake day

`parentskudetail` and the monthly source files cover a period (one day, a week, 28–31 days).
Writing them as "day = first of the month" in `platform_daily_metrics` (the brief's first
proposal) would make every reader that sums by day double-count, and two periods starting the
same day would collide. **New tenant table `platform_period_metrics`**, the same columns as the
daily table plus `period_start`, `period_end` and `variation_id` (`''` = item level), key
`(shop_id, platform, dataset, period_start, period_end, item_id, variation_id, stream, segment,
order_type)`. Datasets: `product_period` (item × variation), `traffic_overview_period` (month ×
L1 source). The gateway accepts `granularity: "period"` for these datasets only (step 2).

### 3. Shopee items, flags and promotions (client lane, tenant-direct)

- **`platform_items`**: `(shop_id, platform, item_id, variation_id)` → name, variation name,
  seller SKU, status, first / last seen. `products` is not widened: its `tiktok_product_id` is
  NOT NULL, and relaxing it is a non-additive change every TikTok reader would feel.
- **`platform_product_flags`**: `(shop_id, platform, item_id, period_start, period_end, flag)`,
  `flag` ∈ {`new_product`, `price_competitive`, `price_uncompetitive`, `ads_grow`,
  `ads_optimize`, `ads_track`}. The flag's own metrics are the item's period metrics and are not
  copied here.
- **`platform_promotions`**: one row per (program, order type): type, name, run dates, status,
  sales, orders, units, buyers, `extra`. Shopee exports no program id; the key is `(shop_id,
  platform, promo_type, program_name, starts_on, order_type)`. The program name is the seller's
  own listing text, not buyer text, so it is stored as a column (D16 drops strings only from the
  open `extra`).
- **Ads by campaign (G11)**: the dataset name `ads_campaign_daily` is reserved; its row shape is
  fixed when the first campaign export (or the Ads API) is seen, not guessed now.

All four are `tenant_direct` (RLS on `shop_id`, `juli_app` SELECT / INSERT / UPDATE) and are
written by the gateway path only, like `platform_daily_metrics`.

### 4. Contract KPIs, lever plans and forecasts are Ops tables (G6, G7, G9)

Contract terms, internal change assumptions and forecasts are never shown to the seller
(disclosure rule; simulator scope rule D42 G4). They are **`ops_only`** like the 083 tables: RLS
on, one policy `TO juli_ops`, no grant to `juli_app`, `anon` or `authenticated`.

- **`kpi_contracts`**: one row per **version** of a shop's contract KPI appendix: `contract_ref`,
  `version`, `status` (`draft`, `sent`, `signed`, `superseded`), `sent_on`, `signed_on`,
  `measure_start`, `params` (the appendix parameters: pass / target levels, D clamp, data-
  sufficiency thresholds, stability windows), `email_ref` (the confirming email: date + subject),
  `created_by` (ops staff). Unique `(shop_id, contract_ref, version)`. An adjustment never edits a
  row: it inserts version n+1 and marks n `superseded` (G7).
- **`kpi_targets`** (per version × flow × metric): `role` (`kpi` | `tracking`), `baseline`,
  `d_pct`, `pass_level`, `target_level`, `window_days`.
- **`kpi_adjustments`** (append-only): what changed from the previous version, with
  `effective_on` and `email_ref`.
- **`kpi_exclusions`** (per version × day): excluded days and why (double days ± pad, extra days).
- **`lever_plans`**: one editable row per lever effect: `lever_key`, `wave`, `name`, `starts_on`,
  `lag_days`, `flow`, `metric`, `low`, `high`, `enabled`, optional `scenario_id` →
  `ops_sim_scenarios` (G9).
- **`kpi_forecasts`** (append-only): one row per job run × flow × metric × milestone: `expected`,
  `lo90`, `hi90`, `p_pass`, `trend_weight`, `inputs_sha256`, `method_version`. The job (step 3)
  writes; Mô phỏng reads.

Per-client model parameters and forecasts are client data (ADR-116 §3, C9): offboarding (T8)
deletes these rows with the shop's data; the deletion runs as the migration role, so `juli_ops`
gets no DELETE on the append-only tables.

### 5. Public Shopee market lane (G10)

Public search pages are the public lane (ADR-116 §1): no `shop_id`, shared, allowed in shared
models. Two tables, `ops_only` until a seller-facing reader exists:

- **`market_listing_snapshots`**: one row per card seen: `platform`, `keyword`, `category`,
  `sort`, `page`, `pos`, `collected_at`, `platform_item_id`, `platform_shop_id` (the platform's
  shop id, named so the tenant sweep never mistakes it for Juli's `shop_id`), `title`, `price`,
  `discount_pct`, `rating`, `sold_text`, `sold_monthly`, `sold_lifetime`, `collector`, `extra`.
  Unique `(platform, keyword, sort, page, pos, collected_at)`. `page` / `pos` are provenance
  only, never a model feature (D61.9).
- **`market_keyword_snapshots`**: one row per keyword × sort × collection day: card / shop
  counts, median page-1 price, discount share, monthly sold median / P75, `extra`.

The loader skips `test_split/` (ml_guard's frozen test sets are never loaded anywhere).
Column widths were checked against the 2026-10-29 collection (36 keywords) and Ory's export
set: every value fits; `sold_text` is 120 because some card lines run that long. 65 cards of
that collection carry no `item_id` (not a product card); the loader counts and skips them.

### 6. Where data may live (G1, G8)

Same schema everywhere; the **target URL** decides. Until Ory approves sub-processor list v2
(C13 / D8), Ory's client-lane rows exist only in a local Postgres (Docker, UTC, `alembic upgrade
head`), with a local-only `service` consent row. Juli's own shops and the public lane may go to
Supabase now. When v2 is approved the loader is re-run against Supabase; no code changes.

## Consequences

- One migration (`108_shopee_ops_data`), expand-only: one nullable column and twelve new tables;
  no data change; `downgrade` drops them. The deferred tail (101 → 074) is re-parented onto 108.
- Step 2 extends the gateway (`granularity: "period"`, the new datasets and the L2 segment
  table, `mapper_version` on write) and adds the file loader; step 3 ports the KPI / expected-
  move / CTR jobs; step 4 builds the dashboards. None of those changes this schema's keys.
- `source_rank` stays api 3 > file 2: the reconciliation report (30 overlapping days before file
  loading stops) compares rows on the same key, using `mapper_version` to separate mapping from
  data changes.

## Alternatives rejected

- **Period rows in `platform_daily_metrics` as day = month start** — double counts and key
  collisions (§2).
- **Widening `products` for Shopee** — needs `tiktok_product_id` nullable, a non-additive change
  on a table every TikTok path reads.
- **KPI contracts as tenant tables** — the seller app would get a grant on contract terms and
  forecasts it must never show.
- **A new stream per L2 source** — G3 keeps the four streams; L2 is a breakdown, not a stream.
