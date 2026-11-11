# P100 Session 2 — ISV demo client ("Dữ liệu mẫu" shop)

Started 2026-11-11, in parallel with Session 1 (`p100-a/b/c/g`). Source: `p100-session-briefs.md`
§B.2, §B.18, §B.22–23, §F. Base: `fasttrack/p99-combo` 250217be + 55922fb7 (§J).
Standing rules unchanged (ask before push/tag/SSH/merge; never write Fujiwa `2b1da87b-…` or
ORY; synthetic data only in the repo; the owner runs every prod command).

## What exists today (read 2026-11-11)

- No Shopee sample shop. The sample modes (`demo-landing`, `no-shop-sample-strip`,
  `lib/quyet-dinh/sample-data.ts`, reviewer `sample`) are client-side fixtures, TikTok-era.
- The reviewer account (`services/reviewer/`, migration 090) pins shops through
  `REVIEWER_SHOP_IDS`; `sandbox.pin_mode` gives `sandbox` (Juli's TikTok sandbox shop, live
  writes) or `masked` (any other shop: identity mask on, read-only, simulated Duyệt/Thực thi).
- Shopee data enters only through `POST /v1/ingest/{platform}/{dataset}`
  (`services/ingest/gateway.py`, datasets in `services/ingest/mapping.py:DATASETS`, row models in
  `services/ingest/schemas.py`), then `materialize.after_ingest` rebuilds
  `shopee_*_metrics_daily`. Costs (giá vốn) come from `services/shop_inputs`.
- `Shop` has no sample/synthetic flag.

## Slices that can start now (no file overlap with Session 1)

### S2-A — synthetic shop generator + loader (data-platform)
- `scripts/sample_shop/`: a deterministic generator (fixed seed) of a minimal Shopee shop: 6
  products (household goods, synthetic brand and names, ORY-like price/AOV/traffic shapes,
  1–3 variations each), 90 days ending on a given date, every day present. It produces
  **Connector-shaped `IngestBody` rows** for the datasets the Shopee screens read (orders +
  income, catalog/snapshot, shop + product + per-source traffic, ads campaign daily, promotions
  incl. one running Combo Khuyến Mãi) plus the shop-input costs, so the shop goes through the
  same gateway → materialize path as a real Connector.
- Loader: `--dry-run` (writes JSONL only), in-process `--database-url` (local), never a default
  remote DB. It creates the shop itself (Shopee platform, name "Dữ liệu mẫu", reserved
  synthetic `shopee_shop_id` range) and **refuses any target shop it did not create** (no
  credentials, id in the reserved range) and the Fujiwa / sandbox ids by name.
- Test: Postgres test DB, generate → ingest → materialize → the Shopee analytics read model
  returns every day, product ≤ shop every day, known-cost profit non-NULL, ads ROAS sane.

### S2-B — reviewer "sample shop" pin mode (backend, security)
- New pin mode `sample` beside `sandbox` / `masked`: a pin listed in `REVIEWER_SAMPLE_SHOP_IDS`
  **and** holding no TikTok/Shopee credentials and no `production_write_shops` row → mask off
  (names are synthetic), writes off, Duyệt/Thực thi simulated exactly as for `masked`. Any check
  failing → `masked` (fail closed).
- `GET /reviewer` exposes the mode; the banner says "Dữ liệu mẫu"; no visible word "demo".

## Later (wait for Session 1)
- S2-C Tự tạo offers only finished strategies (Combo first) — after `p100-c-combo` lands
  (it edits `panels-offers.tsx`).
- S2-D pre-generated titles (≤ 1 live regenerate / product) and banners from the shop
  profile — after Session 1 E.7.
- S2-E prod load: the owner runs the loader against prod after S2-A/B deploy; then pin it.

## Defaults taken (owner may override)
- 90 days, no missing days (a clean shop; the missing-day path is shown on ORY, not here).
- Reviewer reaches the shop through the existing reviewer login, as an extra pin.

## S2-A result — synthetic shop generator + loader (2026-11-11)

Code: `scripts/sample_shop/` (`catalog.py` products and id range, `generator.py` pure/deterministic,
`loader.py` CLI). Owner change applied: **30 days** ending at `--end-date`, every day present.

**Reserved id range.** `shopee_shop_id` 990000000000..990000000999 (12 digits; real Shopee ids
have at most 10), default `990000000001` (`catalog.SAMPLE_SHOPEE_SHOP_ID*`). The loader writes only
a shop in this range, platform shopee, with no TikTok credential / ingest token /
`production_write_shops` row. Fujiwa `2b1da87b-…` and sandbox `1862f13b-…` are refused by id. A
remote database host needs `--allow-remote-database`. Shop name "Dữ liệu mẫu"; `service` consent.

**Datasets generated (Connector-shaped `IngestBody`, source `extension`, VND, rates as fractions):**
`item_catalog`, `item_snapshot` (2 captures), `order_lines` + `order_income` (income for orders
older than 4 days), `shop_overview` / `shop_traffic` / `traffic_overview` (confirmed; plus the ads
row, placed), `item_traffic_sources` (per product x stream x Thẻ-sản-phẩm child, confirmed),
`ads_campaign_daily` (2 campaigns, placed) + `ads_campaign_period`, `promotion_daily` and
`promotions` (one running Combo Khuyến Mãi, 2 tiers: buy 2 -5 %, buy 3 -10 %, the tiers in `extra`
numbers because the gateway stores none). Giá vốn per variation through `shop_inputs.write_versions`
(`sku_cost`, scope `item:model`; a "Combo 3" variation carries the single item's cost, the engine
multiplies by the pack count in the name).

**Run.**
```
python -m scripts.sample_shop --end-date 2026-11-10 --dry-run --out /tmp/sample   # JSONL only
python -m scripts.sample_shop --end-date 2026-11-10 --database-url postgresql://…@127.0.0.1/db
```
`--end-date` must not be after today (GMT+7). Re-running finds the shop by its reserved id and
re-posts identical bodies (all `duplicate`), so it is idempotent. The loader skips the gateway's
per-post materialize hook and runs `backfill_shop` once at the end (same rows, 13x less work).

**No earlier period.** The sample shop has only 30 days, so "30 ngày trước" is empty. Backend: the
overview/matrix payloads carry `warnings: [previous_period_thin]` ("Kỳ trước chưa đủ dữ liệu đơn
hàng để so sánh: các mức tăng / giảm so với kỳ trước được ẩn."), every `kpi_strip.*.previous` and
`change_pct` is `null`. Nothing errors. The product page's 7-day compare still works (the prior 7
days are inside the 30). Whether the web shows no arrow or a dash is a front-end behaviour not
checked here.
