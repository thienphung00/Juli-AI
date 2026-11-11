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
