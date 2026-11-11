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
  1–3 variations each), 30 days ending on a given date, every day present. It produces
  **Connector-shaped `IngestBody` rows** for the datasets the Shopee screens read (orders +
  income, catalog/snapshot, shop + product + per-source traffic, ads campaign daily, promotions
  incl. one running Combo Khuyến Mãi) plus the shop-input costs, so the shop goes through the
  same gateway → materialize path as a real Connector.
- Loader: `--dry-run` (writes JSONL only), in-process `--database-url` (local), never a default
  remote DB. It creates the shop itself (Shopee platform, name "Dữ liệu mẫu", reserved
  synthetic `shopee_shop_id` range) and **refuses any target shop it did not create** (no
  credentials, id in the reserved range) and the Fujiwa / sandbox ids by name.
- Test: Postgres test DB, generate → ingest → materialize → the Shopee analytics read model
  returns all 30 days, product ≤ shop every day, known-cost profit non-NULL, ads ROAS sane.

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
- 30 days (owner, 2026-11-11), no missing days (a clean shop; the missing-day path is shown on
  ORY, not here).
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

### S2-A follow-up: Quyết định cards (2026-11-11)
`scripts/sample_shop/decisions.py`, run by the loader after the backfill, only while the shop has
no proposal (idempotent). Every step uses the app's services with the time it would have happened
(`manual.create_manual`, `service.decide`, `mark_executed`, `change_sets.set_window`,
`verification.verify_shop`, `measure.read_change_sets`, `generate_cards`, `publish`); no number is
written. State after a load on `--end-date` e:
- **Đo lường, finished**: a Voucher (8k, đơn từ 150k, product 1) built e-16, started e-15; its 7-day
  window closed e-8. The generator counts the voucher's use from the simulated orders
  (`shop_voucher_share`, top-up of baskets), posts `voucher_settings` + a `promotions` Voucher row
  with `usage_rate`/`voucher_cost`; `impact_final` (ratio DiD on the product's daily AOV) is read from
  the rows. Window is e-15..e-8, not e-22..e-9: the reading needs 14 days before the change and the
  history has 30. Confidence is "thấp" (`no_controls`: too few comparable products).
- **Đo lường, counting down**: a Tiêu đề (product 4, fixed string `catalog.NEW_TITLE`) applied e-5,
  verified from `item_catalog`, 7-day window open. Old/new title are also in two
  `platform_item_snapshots` rows (the gateway's `item_snapshot` has no title column).
- **Đang thực hiện**: the engine's Ảnh bìa card on product 6, approved, not done yet.
- **Đề xuất**: engine cards as of e: Tiêu đề (product 2, keyword seed "khăn lau bếp"), Ảnh bìa
  (product 5), Voucher (product 3, positive only because the past voucher gives a usage rate), plus
  other kinds S2-C filters out.
Front-end gaps for S2-C: `tabOfCard` puts a *verified executed* card in Đo lường and maps status
`measured` (window closed) to `null`, so the finished voucher is in no tab until `measured` maps to
`do-luong`; the running title is the one in Đo lường today. Đang thực hiện shows only approved or
unverified-executed cards, so the "applied title" cannot sit there once its change is read back.

## Owner decisions 2026-11-11 (after the contract)
- **Reviewer pins = sample shop (default) + TikTok sandbox. Fujiwa is dropped** from
  `REVIEWER_SHOP_IDS` (prod env change, no code). No client data reaches the ISV reviewer,
  masked or not.
- **Only the tabs that work**: in sample mode the Shopee rail shows Tổng quan · Phân tích · Sản phẩm
  · Quyết định; Từ khóa, Quảng cáo, Đơn hàng, Luồng are hidden (not greyed out, no "sắp có"). In
  Tự tạo: **Tiêu đề · Ảnh bìa · Voucher** only (owner, later 2026-11-11: Combo removed); KOL,
  Quảng cáo, Combo nhiều SKU, Combo Khuyến Mãi hidden. Cài đặt menu: Đổi shop · Đăng xuất. Thực hiện =
  checklist. Design: https://claude.ai/artifact/HKYu5uqPX4egtX2cHB6bgK (6 boards).
- New slice **S2-C nav gating** (`lib/app-navigation.ts` sample-mode list + the Tự tạo strategy
  allowlist), after `p100-c-combo` lands (it edits `panels-offers.tsx`).
- **Đề xuất shows the same three kinds only** (Tiêu đề, Ảnh bìa, Voucher); every other generated
  card kind is filtered out in sample mode (part of S2-C). Đang thực hiện and Đo lường must not be
  empty: S2-A follow-up seeds one running Tiêu đề card (day 5/7) and one measured Voucher card
  (actual vs expected) in the same synthetic 30 days.

## Status 2026-11-11 (end of day)
- S2-A `e42ddfbf` on `fasttrack/p100-s2-data`: generator + loader; 24 unit pass, 2 Postgres skipped
  (sandbox) → owner ran both on local Postgres 16: 2/2 pass.
- S2-B `e2a5a189` on `fasttrack/p100-s2-reviewer`: `sample` pin mode; owner ran `-k reviewer` on local Postgres: 282 pass, 0 skip.
- New slice **S2-F reviewer Shopee routes**: every `/v1/demo/shopee/*` route is 403 `read_only` for a
  reviewer today. Needs a reviewed sample-only allowlist (some GETs write, e.g. keywords) and a
  simulated Shopee Duyệt (`POST …/recommendations/{id}/approve`) — touches `shopee-decisions/**`,
  so after Session 1. Also: `lib/reviewer/guide-copy.ts` (still "shop thật, ẩn tên", "Shop TikTok"),
  `dictionary.md` reviewer keys.

## Owner decisions 2026-11-11 (late)
- **Option A: the sample shop accepts Juli's own writes** from a sample-mode reviewer (Chọn, Kế
  hoạch, what-if, Duyệt, Bỏ qua, Đã làm …) — Juli's database only, never anything outbound to Shopee
  (no fill jobs, no Connector work, no platform API). "Đặt lại dữ liệu mẫu" restores the seeded
  state. LLM drafts stay refused until S2-D. Slice **S2-G**.
- **Reviewer guide back to English** (P77 stands); the app stays Vietnamese.
