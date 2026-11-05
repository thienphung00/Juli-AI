# P95 — TikTok Shop parity on Demo: estimate only (recorded 2026-11-05, NOT scheduled)

Owner: record, do not implement — Shopee and the current client come first. Revisit after the Shopee pilot is
stable.

## Ask
Bring the Shopee P90–P92 features (analytics Tổng quan / Phân tích / Sản phẩm / Xếp hạng, Quyết định cards with
versions, Tự tạo phương án builder + compare, plans and measurement, exclusions, giá + biên, Demo pages Từ khóa /
Quảng cáo + khuyến mãi / Đơn hàng / Luồng) to TikTok Shop on Demo for every TikTok seller (e.g. Fujiwa), plus the
TikTok sandbox for the reviewer, and let sellers create Đề xuất themselves on Demo.

## What exists (code read 2026-11-05)
- TikTok client, OAuth, Business advertiser OAuth: `backend/src/juli_backend/integrations/tiktok/` (orders,
  products, inventory, returns, cancellations, settlements, order costs, promotions/coupons, creators, LIVE,
  analytics). Sync: `workers/tasks/shop_ingestion.py`, `services/tiktok/poll_resources.py`, `services/etl/`,
  webhooks. Tables: orders, order_items, order_price_details, order_finance_transactions, settlements, products,
  product_snapshots, shop_daily_products, promotion_activities, creators.
- Required scopes in `services/ops/scopes.py` (3 of 5 names unverified). No ads client (GMV Max / TikTok ads).
- TikTok shops get the legacy Trang chủ / Phân tích / Quyết định (`services/action_cards`, `services/demo_decisions`);
  every P90–P92 route is gated `_shopee(shop)` (409 `not_a_shopee_shop`).
- Reviewer: `services/reviewer/` (`REVIEWER_SHOP_IDS`), sandbox shop 1862f13b (D73), app-review user.

## Reuse vs adapter
- Reusable as is: shopee_profit arithmetic (waterfall, floor, what-if, five numbers), analytics builders
  (overview, matrix, rankings, product, critical), reco evaluate / prediction / plan / measure / versions /
  codes / queue / manual, builder logic.
- Needs a TikTok variant: fee schedule (or actual fees from order_finance_transactions), income/actuals
  (settlements + statement transactions instead of the Shopee Income file), traffic flows (LIVE / video / product
  card / affiliate), loaders (orders → RawLine, shop_daily_products → flows), `kinds.py` (TikTok pages,
  read-back via API; listing changes can be applied by API), priors (Shopee-calibrated → low confidence).
- No TikTok source: ads / GMV Max (Business API access needed), keyword volumes (Ops upload only), affiliate
  scope `affiliate_seller` not requested.

## Phases (agent-days)
| Phase | Work | Size |
|---|---|---|
| P0 | Probe: real scope names, Fujiwa's granted scopes, analytics breakdown and settlement fee fields, GMV Max API path/permission | 2 |
| P1 | TikTok adapter: platform-generic loader interface, order lines + fee actuals, flows, fee table fallback, 90-day backfill for Fujiwa | 8–10 |
| P2 | Analytics screens on TikTok (lift `_shopee` gates, nav, empty states for ads/keywords) | 4–5 |
| P3 | Cards / versions / plans / measurement for TikTok (kinds, generators for promotion / price / listing / affiliate, coexistence or retirement of legacy action_cards) | 7–9 |
| P4 | Seller builder + Đề xuất creation on Demo for TikTok | 3–4 |
| P5 | Ads / GMV Max (blocked on Business API access) | 5–8 |
| P6 | Reviewer sandbox on the new screens (pin, seeded data, platform "tiktok" reviewer accounts, masking audit) | 3–4 |
Total ≈ 25–35 agent-days. Order: P0 → P1 → P2 (Fujiwa sees analytics first) → P3 → P4 → P6; P5 in parallel once
access is confirmed.

## Risks
Unverified scope names and re-consent prompts; no ads API; thin sandbox data (D73: honest empty states, never
seeded fakes on a real shop); no buyer PII (per-buyer voucher limits not enforceable); rate limits on 90-day
backfills; Shopee-calibrated priors; two card systems on one Quyết định page until legacy cards retire.
