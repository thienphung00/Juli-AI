# P90 implementation plan — for owner approval (freeze until approved)

Inputs: `p90-metrics.md` (definitions), `p90-fields.md` (every source field, as built), `p90-coverage.md`
(gap register G-01…G-24), ADR-120, ADR-121. Each step lists what it closes, what it needs, and how it is
accepted. A step starts only when its "needs" are met; acceptance is checked by the orchestrator, not the
agent that built it.

## Step 0 — owner actions (no code)
| # | Action | Closes | Who |
|---|---|---|---|
| 0.1 | Download one month of **Đơn hàng › Xuất** (order export) into `~/.juli-shop-snapshots/sim-pilot/ory/seller_center/<date>/raw/` — headers are captured from it; buyer columns are never read | G-03 | Thiên |
| 0.2 | Grant the sub-account **Tài chính › Doanh thu**; download one month of the income report | G-05 | ORY manager, then Thiên |
| 0.3 | Create ORY's shop in Juli Ops (shop id for the connector pilot gate) | G-16 | Thiên |
| 0.4 | Decisions D-1…D-6 below | G-06, G-08, G-15, G-18, G-20…G-22 | owner |

## Step 1 — loader correctness on ORY's real files
Fix G-01 (conversion rate above 100 % refuses a whole post → drop that derived column, as CTR already is),
G-02 (monthly roll-up shop-stats read as days → detect granularity, route to period rows), G-23 (Flash
Sale daily rows from two files on one key → one owner), parser tests for `parse_product_overview` and
`parse_shop_traffic`.
**Accept:** `--dry-run` on all five ORY raw folders: zero refusals; every file either posted or listed as
skipped with a reason; fixtures reproduce G-01 and G-02 (synthetic numbers).

## Step 2 — orders and migration 113
Order-export parser (headers from 0.1) with the PII strip in the browser uploader (name, phone, address
never read; order id → keyed hash, same key as the affiliate lane); status → `OrderStatus`; migration 113:
`shopee_order_lines.buyer_shipping_fee`, `bank_promo`, `ad_attributed` (nullable), tables `shop_health_daily`,
`ads_change_log`; register the reserved datasets (`affiliate_order_lines`, `ads_change_log`, `item_snapshot`,
`shop_health_daily`).
**Accept:** PII canary test (buyer columns + canary id never in any post, summary or log); October 2026
reproduces ORY's own totals from the export alone: 121 orders 01–28/10, AOV 172.025đ (± rounding); Σ
order-line GMV vs shop-stats GMV within 2 %; affiliate order lines join to orders by the same hash.

## Step 3 — fees
Income-export parser (actual fees win, §4); fee table seeded from the 23/05/2026 PDF (§10a) as
`platform_fee_formulas` rows; item → category join (keep `L1/L2/L3 Ngành hàng toàn cầu` from the affiliate
report; product category from the connector when available).
**Accept:** formula fee vs actual fee per delivered order within 1 % for ≥ 95 % of orders (differences listed
by component); every ORY product mapped to a category or listed as unmapped.

## Step 4 — seller import (Cài đặt › Thông số shop)
Template (pre-filled from the product list), validation, diff, versioned apply into `shop_rule_versions`,
restore; new rule keys (packaging, stock, restock date, group, status, monthly GMV / orders / AOV /
margin target, daily marketing cap).
**Accept:** the 4 rejection cases of the artboard; restore creates a new version; only affected
recommendations re-run (test counts them).

## Step 5 — product data and connector live check
`item_snapshot` mapper to `platform_item_snapshots` (write on change, image copies); connector pilot gate =
ORY only (0.3); one live run on the owner's Seller Centre tab.
**Accept:** money units confirmed against 3 known prices; product list count = Seller Centre's (114);
ads daily for yesterday = the Seller Centre screen for the same day; nothing clicked (event log).

## Step 6 — precedence and naming (after D-1…D-6)
Source ranks (file vs connector), the `the_san_pham` naming (G-20), GMV column (G-21), ad spend primary
source (G-07), voucher join (G-14).
**Accept:** one test per conflict pair asserting which value wins.

## Step 7 — calculations on real data
Wire `services/shopee_profit` to stored data: five flows (shop level; product level per D-1), levers,
product and shop profit with coverage, five numbers, floors with real fee rates, voucher what-if.
**Accept (ORY reconciliation):** Nhóm per-product spend sums to the campaign (8.146.632đ) and ROAS 5,44;
voucher cost = value × orders for every voucher in Nov 2025–Oct 2026; affiliate October 33 orders /
5,0 triệu; flows add up to shop GMV (residual row shown); lever split adds up; coverage flag below 100 %.

## Step 8 — models and simulation (ADR-121)
Lift model ported to Shopee; frozen predictions; Shopee impact reader; natural-experiment backfill (ad
change log, vouchers); calibration + coverage jobs; acceptance statistics; simulation port + priors/v1
import, gated per change_kind.
**Accept:** synthetic-uplift recovery (ADR-077 §6); coverage report on the backfill; simulation gate
decision recorded per change_kind.

## Step 9 — UI (after design approval)
Tổng quan, Phân tích, Sản phẩm, Quyết định card, Cài đặt import — matching the approved artboards and
`VERIFY.md` link table.
**Accept:** Playwright: every link in `VERIFY.md` lands on the right screen with the right parameters; the
same product shows the same numbers on every screen; no buyer data in any response.

## Decisions needed before Step 6/7
- **D-1 (G-06)** Per-product flows: the product export has only the four L1 sources (no Trang shop child) →
  product rows show 4 flows; the 5-flow split exists at shop level only.
- **D-2 (G-08)** Ads are reported on placed orders only → ads figures are labelled "đơn đã đặt"; never mixed
  into confirmed totals.
- **D-3 (G-18)** No source says which flow an ad order lands in → ads "trong đó" shown at shop and product
  level, not per flow.
- **D-4 (G-20/G-21)** Rename the P90 key to `the_san_pham_khac`; GMV = `Tổng doanh số (VND)`.
- **D-5 (G-22)** Precedence: the file (has the Thẻ sản phẩm children) outranks the connector for the same
  day; the connector fills days no file covers.
- **D-6 (G-15)** Affiliate commission source: checked 2026-11-03 — Σ per-line `Chi phí(₫)` in the conversion
  report does NOT reconcile with the ValidationBill month on the files held (the report covers a partial
  window; the bill's `Hoa hồng hằng tháng` also needs its number format confirmed). Open: download one
  full-month conversion report for a settled month and re-check before choosing the column.

## Owner answers (2026-11-03)
- **D-2/D-3 approved:** ads labelled "đơn đã đặt", never mixed into confirmed totals; "trong đó" at shop and
  product level, not per flow.
- **D-4 approved:** new key `the_san_pham_khac` for "Thẻ sản phẩm ngoài Trang shop" (existing `the_san_pham`
  keeps its meaning); GMV = `Tổng doanh số (VND)`.
- **D-5 approved:** file outranks connector for the same day; connector fills uncovered days; differences logged.
- **D-1 resolved (owner was right):** Seller Centre's product detail page returns, per product, the Thẻ sản
  phẩm breakdown incl. `psd_label_shop` (Cửa hàng = Trang shop), Tìm kiếm, Đề xuất, Giỏ hàng, Đơn mua, Khuyến
  mãi, Khác (`/api/mydata/v1/product/traffic/details/`, recon doc). Products get all five flows. Source: a new
  connector reader (one call per product per finished day, paced) — the monthly export stays 4 flows and is
  used only where the connector has no day. Closes G-06 (moved to Step 5).
