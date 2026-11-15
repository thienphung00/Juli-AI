# Metric registry and platform capabilities — design (draft 2, 2026-11-15, owner decisions in)

Owner decisions: T5 (four layers, platform-neutral tables), T6 (one calculation everywhere),
T8 (headline GMV = the platform's reported shop totals), T9 (capabilities per platform), from
`~/Juli-AI-v2/tiktok-parity-grill-2026-11-15.md`. Requirements: ORY's report request
(`~/Juli-AI-v2/ory-report-calc-audit-2026-11-15.md` §1–3 and asks 1–10). Owner: Session 1.
TikTok rows: the TikTok session (juli-ai-v2-27). Sample shop: Session 2 (juli-ai-v2-ed).

## 1. Why

Today one name gives different numbers on different screens. The inventory of 2026-11-15
found four live shop-profit values, ≥ 6 margin definitions, three AOVs, two "ưu đãi" formulas,
three "ROI"s, six ad-spend resolvers, three GMV-impact decompositions, two stock-cover
forecasts, and order lines dated in UTC while shop totals are GMT+7 (§9). ORY's October report
(21,68 tr · 125 đơn · 2,87 tr) cannot be reproduced from today's data (21 336 200 · 123 ·
2 838 185) because nothing records which data and which formula produced it.

## 2. Rules (binding)

1. Every number a seller, Ops, a reviewer, the recommender, the measurement, an export or an
   agent tool sees is a **registry metric**: an id with one formula over canonical components.
2. **Ratios are computed from summed components**, never averaged and never in the frontend.
   The frontend formats (and computes only "Thay đổi" from two API values and "/ ngày" for a
   summable metric — both registry helpers, generated to TS).
3. **Missing is not zero**: a component without data is `None`; a metric over it is `None`
   (or `partial` with its coverage), never 0.
4. **Headline volume is platform-reported** (T8): `gmv`, `orders` = the platform's shop totals
   (Shopee: Seller Centre shop_overview, confirmed). `net_revenue` (Doanh thu thực) sits beside
   them. **Profit and margins are always on net revenue.**
5. Every value carries `basis` (platform / juli / estimated), `as_of` (the data day), and the
   `derivation_version` that built it. Exports print them (ask 9); a report can be rebuilt.
6. Platform-neutral names. A metric's per-platform source is data in the registry, not an
   `if shopee:` in a screen.

## 3. Modules

| Path | Holds |
|---|---|
| `backend/src/juli_backend/services/metrics/registry.py` | `MetricDef` + `METRICS: dict[str, MetricDef]` (ids below), `DERIVATION_VERSION` |
| `backend/src/juli_backend/services/metrics/components.py` | canonical components per scope/window (sums only), read from layer-4 tables |
| `backend/src/juli_backend/services/metrics/compute.py` | `value(metric_id, scope, window) → MetricValue` and `values(...)` (batch); the only place formulas run |
| `backend/src/juli_backend/services/metrics/allocation.py` | written rules: channels (§6), ads to products, "Cả shop" lines (§7) |
| `backend/src/juli_backend/services/capabilities/registry.py` | T9: `can(platform, capability) → Capability(route: api \| connector \| none, reason)` |
| `apps/demo/src/lib/metrics/registry.generated.ts` | generated ids, labels, units, rounding, `summable`, `perDayAllowed`; never hand-edited |
| `scripts/gen_metric_contract.py` | writes the TS file; CI fails when it is stale |

`MetricDef` fields: `id`, `label_vi`, `unit` (vnd · count · ratio · pct_points · days · x),
`rounding` (`shopee_profit/money.py` rules: đồng half-up, % 0.1, x 0.1), `formula` (over
component ids), `summable` (can be added over days/products/shops), `window` (anchor rule:
`anchor_day` = last complete day of the platform's shop totals; `previous` = same length
before; `month` = calendar month for "vs tháng trước"), `levels` (shop / product / sku /
channel / kol / business), `sources: dict[platform, SourceSpec]` (dataset, order basis,
field), `basis` (platform / juli / estimated), `none_rule`.

`MetricValue`: `value`, `basis`, `coverage` (0–1, for cost-dependent metrics), `as_of`,
`derivation_version`, `partial: bool`.

## 4. Canonical components (layer 4, per platform, per day, per scope)

`gmv`, `orders`, `units` (platform shop totals) · `line_gmv`, `line_orders`,
`line_units` (order lines, confirmed, **GMT+7 day**) · `net_revenue` (buyer paid: deal×qty −
seller voucher − combo − output VAT; 0 for an accepted refund) · `cogs` (+ `cogs_known_gmv`) ·
`packaging` · `fees` · `shipping_net` · `ads_spend` (one resolver: §5) · `ads_gmv_platform`
· `affiliate_commission` · `offer_promo`, `offer_voucher`, `offer_combo` · `other_marketing`
· `views`, `clicks` (per source) · `samples_cost` · `stock_units`.

## 5. Metric ids (Shopee source shown; TikTok column filled by the TikTok session)

### Volume
| id | Label | Formula | Summable | Shopee source |
|---|---|---|---|---|
| `gmv` | GMV | Σ gmv | yes | shop_overview, confirmed (platform) |
| `orders` | Đơn | Σ orders | yes | shop_overview, confirmed |
| `units` | Sản phẩm bán | Σ units | yes | shop_overview |
| `aov` | AOV | gmv ÷ orders | no | — |
| `net_revenue` | Doanh thu thực | Σ net_revenue | yes | order lines (juli) |

Retired: `aov_seller_centre` (screen line), five-numbers line AOV (uses `aov`), every
`line_gmv ÷ line_orders` shown as AOV.

### Profit and margin (two labelled margins, ask 1)
| id | Label | Formula |
|---|---|---|
| `profit` | Lợi nhuận | net_revenue − cogs − packaging − fees − shipping_net − affiliate_commission − ads_spend − other_marketing, on **known-cost orders** (today's `known_cost_profit`); `coverage` = known-cost GMV share; `partial` below 100 % |
| `margin` | Biên lợi nhuận | profit ÷ net_revenue (same known-cost orders) |
| `margin_sale` | Biên ở giá bán | one unit at the selling price: (revenue after VAT − fees − cogs − packaging) ÷ revenue after VAT; product/SKU only; no marketing |
| `contribution` | Lợi nhuận trước quảng cáo | profit + ads_spend (used by break-even ROAS, KOL net) |

Retired: `ShopMetrics.profit` scaled by GMV ÷ line GMV (metrics.py:315-332) and the stored
`*_metrics_daily.profit` built from it (rebuilt as `profit` per day, T3); `profit_on_covered`
as a shown value; `margin_final` (Biên cuối); builder card margin on GMV (→ `margin`).
Product profit = the same formula on the product's lines **after ad allocation (§7)**, so
Σ product profit + "Cả shop" lines = shop profit exactly.

### Costs (ask 2: every cost line + % of net revenue, same list per product)
`cost_cogs`, `cost_packaging`, `cost_fees`, `cost_shipping`, `cost_ads`, `cost_affiliate`,
`cost_offers` (= `offer_promo + offer_voucher + offer_combo`, on non-cancelled confirmed lines;
parts shown as sub-lines), `cost_other`, `cost_total` (Σ all), `cost_marketing` (ads +
affiliate + offers), and for each `*_pct` = cost ÷ net_revenue. Retired: `exports/collect.
_offer_cost` (voucher + combo, skipped in-transit).

### Returns on cost
| id | Label | Formula |
|---|---|---|
| `roi` | ROI | profit ÷ cost_marketing (shop, product, channel) |
| `roas` | ROAS | ads_gmv_platform ÷ cost_ads (Shopee broad, placed — labelled) |
| `roas_direct` | ROAS trực tiếp | direct ads GMV ÷ cost_ads |
| `roas_break_even` | ROAS hoà vốn | net_revenue ÷ contribution |
| `roi_kol` | ROI KOL | (kol_net − samples_cost) ÷ (kol_commission + samples_cost) — one function (today ×3) |
| `card_return` | ΔGMV / chi phí | a card's ΔGMV ÷ its cost — not labelled "ROI" any more |

### Funnel, channels, stock, KOL
`views`, `clicks`, `ctr` (clicks ÷ views), `ctor` (orders ÷ clicks), `ctr_ads`, `ctor_ads`
(days with both counts, #2294) · `channel_gmv[organic|ads|affiliate]`, `channel_share`,
`channel_profit`, `channel_cost_pct` (§6) · `units_per_day`, `days_left`, `runs_out_on`,
`restock_units` = units_per_day × (lead_time + cover) − stock (lead time a shop rule) — the
stock-alert forecast is the **only** forecast; the product page reads it · `kol_gmv`,
`kol_share` (of **shop** gmv, ask 8), `kol_commission`, `kol_net`, `kol_status`
(owner 2026-11-15: no fixed rule — decided by the KOC's own data): the 90 % confidence
interval of `roi_kol` from its order-level net profit after samples over the period —
**Hiệu quả** when the lower bound > 1, **Không hiệu quả** when the upper bound < 1, else
**Chưa đủ dữ liệu**; `kol_share` is shown beside it and does not decide it · reco/measurement
keep their P10/P50/P90 deltas but compute them on these ids.

### Comparisons (ask 3)
Every KPI exposes `prev` (same-length previous window), `month_prev` (previous calendar month,
month-to-date matched) and `target` (shop_rules); "Thay đổi" = value ÷ ref − 1 (registry helper).

## 6. Channel basis (non-overlapping, ask 4)

traffic_overview sources overlap (ORY Oct: 56,9 tr / 343 đơn vs shop 21,3 tr / 123), so shares
on it are not % of revenue. Rule: partition **shop gmv** in this order —
1. `affiliate` = GMV of affiliate-attributed confirmed order lines (KOL report join), scaled to
   shop totals;
2. `ads` = ads-attributed confirmed GMV (overlay / ads report confirmed share), capped at
   gmv − affiliate;
3. `organic` = gmv − affiliate − ads (≥ 0).
Channel profit = channel net revenue × the shop's contribution rate − the channel's own cost
(ads → ads channel, commission → affiliate). Traffic views/clicks stay per source for the funnel
only. An order both affiliate- and ads-attributed counts as **affiliate** (owner 2026-11-15:
the commission is the cost that order adds).

## 7. Allocation and the "Cả shop" lines (ask 6)

Ads to products: campaign/group rows with a product id go to that product; the rest stays
**"Quảng cáo chưa gán sản phẩm"** (no hidden spread). The product sheet's last block is labelled
lines that add up to the shop:
- Quảng cáo chưa gán sản phẩm (= cost_ads − Σ product ads; ORY Oct: −3 397 017)
- Chi phí marketing khác (other_marketing)
- Chênh lệch cơ sở (shop totals gmv − Σ product gmv from lines; orders likewise)
No ROI, no margin on these lines.

## 8. Capabilities (T9)

`can(platform, capability) → Capability(route, reason)`; capabilities: `read_orders`,
`read_shop_totals`, `read_ads`, `write_price`, `write_listing`, `write_stock`, `promo_discount`,
`promo_flash_sale`, `voucher`, `bundle`, `affiliate_commission`, `ads_campaign`,
`live_schedule`, `shop_tab`. Replaces `_shopee()` in routes and the frontend platform checks;
the Tự tạo builder offers only what `can()` allows (T10). Shopee rows (today): reads =
connector (shop_overview, order pages, ads pages), listing/price/promotions/voucher/bundle/
ads = connector (fill, seller presses Lưu). TikTok rows: TikTok session.

## 9. Fixes the registry lands first (in this order)

1. One `profit` (known-cost) everywhere; remove the scaled variant and rebuild stored rows (T3).
2. One `cost_offers`; the export uses it (period total = Σ days).
3. Two margins (`margin`, `margin_sale`); builder card margin on net revenue.
4. Order-line day in GMT+7 (UTC-naive `ordered_at` today moves orders across midnight).
5. `days_left` from the forecast on the product page (FE StockBlock stops computing).
6. "Cả shop" labelled lines (§7) + export `as_of` / `derivation_version` / basis per number.
7. Channel partition (§6) on Tổng quan, Phân tích and the export.
8. ROI family renamed (`roi`, `roi_kol`, `card_return`), one KOL ROI function.

## 10. Enforcement

- **Contract test** (Python ↔ TS): the generated TS equals the registry (ids, units, rounding,
  summable).
- **Golden test**: for a seeded shop and window, every endpoint that returns metric X (Tổng
  quan, Phân tích, Sản phẩm, Kế hoạch, Ops viewer, reviewer, export, agent tool) returns the
  same value for X. Starts with gmv, orders, aov, profit, margin, cost_total, roi.
- **Ban test**: no division producing a shown metric outside `services/metrics/` (allowlist
  shrinks to empty as screens migrate); no ratio computed in `apps/demo/src` outside the
  generated helpers.
- **Nightly consistency sweep** (T6): recompute a sample of (shop, metric, window) from raw and
  compare with stored; repair or alert.
- **Acceptance case**: ORY October 2026 (audit §5) — gmv 21 336 200, orders 123, cost_ads
  3 397 017, profit 2 838 185, coverage 1.0, "Quảng cáo chưa gán sản phẩm" −3 397 017, each with
  as_of and derivation_version.

## 11. Owner decisions (2026-11-15)

1. §6: an order both affiliate- and ads-attributed counts as **affiliate**.
2. KOC: **no fixed rule**; `kol_status` from the confidence interval of `roi_kol` (§5).
3. Restock defaults: `lead_time` 7 + `cover` 14 days, per-shop rules (ORY's answer to the
   2026-11-14 restock question overrides).
4. Packaging with no rule: **keep 0**, `cost_packaging` flagged "chưa nhập chi phí đóng gói"
   (coverage, not an estimate).
