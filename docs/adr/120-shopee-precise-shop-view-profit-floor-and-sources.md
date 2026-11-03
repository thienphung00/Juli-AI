# ADR-120: Shopee shop view from broad to precise — GMV tree × sources × products, floor price, what-if, history

**Status:** Accepted (owner, 2026-11-03, grill D82)
**Date:** 2026-11-03
**Deciders:** owner (Thiên) with the agent, grounded in the ORY meeting of 03/11/2026 (ORY executive
and manager) and ORY's Seller Centre exports (`~/.juli-shop-snapshots/sim-pilot/ory/seller_center/`).

**Builds on:** [ADR-107](107-card-journey-log-and-measurement-plan.md) (append-only card history),
[ADR-109](109-shopee-isv-resubmission-reviewer-trial-account.md) d.5 (ranking that adds up),
[ADR-116](116-client-data-lanes-consent-and-model-split.md) (lanes, model disclosure),
[ADR-117](117-shopee-seller-centre-files-kpi-contracts-and-public-market-lane.md) (datasets, executors),
[ADR-118](118-shopee-manual-cycle-proposals-approvals-executions.md) (proposals → approvals → executions → results),
[ADR-119](119-shopee-keywords-title-decomposition-and-owner-collected-metrics.md) (keywords).
**Amends:** ADR-117 §6 / C13 / D8 for ORY (see 1); ADR-109's nav (see 2).

## Context

ORY's executive rejected broad, Word-style plans: every proposal must trace to data, state its
discount as a percent, and show the final margin after platform fees and costs. ORY's cost of
goods is not one third of the price (túi đay: 65.000đ cost, 89.000đ price). The monthly plan has to
scale from 9 products to 50 without more manual work. No Shopee Open Platform app exists yet.

## Decisions

1. **ORY data may live on the hosted backend.** ORY approved the sub-processor list (owner,
   2026-11-03). The local-only rule of ADR-117 §6 / C13 / D8 is lifted for ORY; the loader's
   `--allow-remote-database` default stays for every other client. No buyer PII, ever: order and
   income exports are stripped in the browser (name, phone, address dropped; order id → keyed hash).
2. **Nav: Tổng quan / Phân tích / Sản phẩm (+ sub-tabs) / Quyết định; Cài đặt in the avatar menu.**
   Tổng quan replaces Trang chủ for Shopee shops. Coordinated with P81 (app shell).
3. **Tổng quan = GMV tree × sources × products.** KPI chain Lượt xem → CTR → CTOR → AOV → GMV →
   Biên lợi nhuận; north star GMV for the shop, profit per product and per source. Two source
   dimensions, each summing to 100 % of orders: **traffic** (Tự nhiên: Tìm kiếm / Đề xuất / Trang
   shop; Liên kết; Flash Sale page) and **price lever per order line** (Không ưu đãi / Voucher /
   Khuyến mãi incl. Flash Sale price / Combo-Mua kèm). **Quảng cáo is an overlay** ("trong đó"):
   Shopee also counts ad orders inside Tìm kiếm / Đề xuất, so it is never added.
4. **The executive's five numbers head every view and card, in VND and %:** ① % giảm giá,
   ② doanh thu tăng thêm / chi thêm, ③ biên lợi nhuận cuối, ④ số đơn, ⑤ AOV — plus the spend cap.
5. **Ranking is kept and extended** (ADR-109 d.5): any KPI opens a ranking whose rows add up to the
   cell; a source chip filters it, a "Xếp theo" switch sorts by ₫ GMV/ngày (default), ₫ lợi
   nhuận/ngày or any of the five numbers; row kinds follow the source (products, campaigns, KOLs,
   vouchers / programmes, keywords). Every row carries "→ đề xuất" with the ₫ it can win or save.
6. **Critical metric** = outside the flow-baseline band, below target, below the floor price / ROAS
   below break-even, or behind the shop median; ranked by ₫ at stake. One change per product per
   measurement window (ADR-106/107), or changes measured as one bundle.
7. **Red line = floor price per SKU.** Absolute floor = (giá vốn + đóng gói + phí cố định/đơn) ÷
   (1 − phí sàn %). Operating floor adds ads %, affiliate commission % and the target margin to the
   denominator. Max discount = 1 − operating floor ÷ list price, capped by the seller's own limit.
   Fee formulas are versioned by effective date and checked against the income export.
8. **Ads carry a purpose:** `hien_thi` (judged on cost per 1 000 views, CTR), `luot_vao_shop`,
   `chuyen_doi` (ROAS vs break-even), `ra_mat` (launch; budget cap and end date, not the 40 % line).
9. **What-if on cards:** a *chắc chắn* layer recomputed from real order lines (qualifying orders,
   discount %, margin per order, floor breach, break-even extra orders) and a *dự kiến* range.
   Models are never disclosed to the seller; their results may be (ADR-116 as clarified 03/11).
10. **Product page** opens with the listing as on Shopee (image + version history, Mã SP, SKU,
    category, status, price block with floor and max discount, stock with days to sell-out,
    reputation, variations, per-block freshness). New append-only `platform_item_snapshots`
    (written on change) and private image copies (`product_image_assets`).
11. **Keyword key list: up to 5 "Chính" keywords per product** plus Phụ / Thương hiệu / Loại trừ;
    the profile shows volume, difficulty, CPC, in-title position, search rank and market price.
12. **Seller inputs are imported** from a pre-filled template (cost, packaging, max discount, stock,
    restock, group, status; monthly targets), versioned in `shop_rule_versions` (append-only;
    `shop_rules` stays the projection), restorable, and re-running only the affected cards.
13. **History:** ADR-107 / ADR-118 events plus `whatif_adjusted` (inputs from → to, outcome shown).
    The ORY manager approves; the Juli team executes; the executive monitors.
14. **Collection before the API:** (A) Ops multi-file upload with type detection now; (C) the Juli
    Connector reads more Seller Centre pages and **may open the report pages itself on a schedule**
    (owner-approved; read-only, the seller's own session, stop on CAPTCHA, allowed-pages list
    updated); (D) the connector triggers Seller Centre's own exports for file-only reports;
    (E) market module for keyword lookups and search captures from the operator's browser.
    Third-party Shopee tools are not used. Every source writes the dataset keys an API executor
    will use later.

## Consequences

- Migration 112: `platform_item_snapshots`, `product_image_assets`, `shopee_order_lines`,
  `platform_fee_formulas`, `shop_rule_versions`, keyword roles, `ad_campaign_purposes`,
  `whatif_adjusted` events.
- A pure calculation package (`services/shopee_profit/`) owns fees, order-line profit, floors,
  what-if, the five numbers and the source matrix; routes and UI read it.
- Fee components and the per-SKU cost are inputs; until they exist, floors and margins show
  "chưa có giá vốn" instead of an estimate. The one-third assumption is retired.
- Design artboards in `docs/product/design/shopee-shop/` must be owner-approved before UI code.

## Alternatives rejected

- **Cost = one third of price** — contradicted by ORY's own numbers.
- **Ads as an additive source** — double counts orders Shopee also files under search/recommend.
- **A 40 % ad-cost line for every ad** — wrong for views and launch ads; replaced by purpose.
- **Third-party Shopee tools with API approval** — adds a sub-processor and a foreign schema.
- **One top-level tab per aspect** — breaks the mobile bar; aspects are sources inside the views.
