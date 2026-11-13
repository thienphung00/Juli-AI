# backend/src/juli_backend/services/shopee_builder

## Purpose

P92 "Tự tạo phương án" (`fasttrack/contracts/p92-plan.md`, API contract
`fasttrack/contracts/p92-api.md`): the builder's backend. It owns **no formula**. A typed version
(one model per strategy, `specs`) becomes a variant (`translate`), the existing recommendation
machinery builds its card (`shopee_recommendations.manual.build_variant`: evaluators, lift model,
floors, spend check), and `outcome` lays the same block out for every kind (driver metric(s), Δ GMV /
orders / profit as low-P50-high, margin after, cost of the change, break-even as extra orders AND CTOR,
estimate basis, warnings).

## Layers

| Module | Role |
|---|---|
| `specs` | pydantic models, one per kind, hard bounds; `items_of` lists the listings a version names |
| `context` | `BuilderContext` (the 30-day `RecoEnv`, the variation rows, the 90-day view, keyword facts), `SpecRefused` |
| `translate` | `to_variant`: typed version -> `manual` variant; a shadow `estimate` variant for a variation set |
| `outcome` | `shape` / `refused`: the B-3 block, `DRIVERS`, `BASIS_LABELS`, break-even, cost per kind |
| `traffic` | orders / clicks of a scope from the flow tables; the CTOR a break-even takes |
| `variations` | B-2: list / selling price, pack count, price per unit, VAT-aware margin, "chưa tính" |
| `catalogue` | B-1: the product picker (catalogue + order lines, 90-day GMV, has_cost, excluded) |
| `picker_table` | P97 D85.12: the table picker's filter columns (category, biên, CTOR vs the 30 days before, có đề xuất, đang chạy QC / KOL) |
| `multi` | P97 D85.13: the target list of a version (`sum` / `joint`) and its expansion into one single-target version per target |
| `copurchase` | "Sản phẩm hay mua cùng" from order lines |
| `response` | the product's own (then the other products') orders response to a price cut -> `prediction` |
| `keywords` | the keyword table of a product: title seeds, suggestions, competitor phrases, ads report |
| `drafts`, `llm` | LLM drafts (titles, cover overlay concepts, description first lines) behind `LLMClient` |
| `unit_price`, `market_price` | B-10 "Giá thị trường": pack-normalised price per unit (hộp / 100 cái / 500 ml / 100 g / cuộn) of the public search cards the Connector collects (`market_search`), per-unit median / P25 / P75, the 5 closest similar cards, stale after 14 days; absent (never invented) without a capture. Public tables are read in an `ops_role` block |
| `service` | loading, `evaluate_versions`, `choose` (through `manual.create_manual`), draft facts |

## Rules

- A listing without a giá vốn can be built: profit and margin are `None` / `chua_tinh`, never the
  1/3-of-price fallback (B-7.1). GMV and orders are still shown.
- An excluded listing has no builder entry: `manual.build_variant` refuses it (`item_excluded`). Its
  sales stay in every shop total; `excluded_summary` gives the Tổng quan line.
- Breaches (floor, shop spend cap `daily_marketing_cap`) warn and never block; `choose` needs
  `acknowledge_breaches` for the P91 warning dialog.
- Estimate basis: `product_history` (this product's days with / without a cut) > `shop` (the other
  products' median, or the shop's measured calibration) > `prior` > `insufficient` (no volume could be
  predicted: bands are `null`, not 0).
- The LLM writes words only. Cover numbers come from the product's own prices; a title is <= 100
  characters, holds every ticked keyword, has no banned term and no certification / ingredient /
  price / percent the facts do not state. Off (switch, key or consent) = 503 `llm_off` "LLM tắt".

## Must not

- Re-implement an evaluator, a fee or a floor; extend `shopee_recommendations` instead.
- Put a buyer field, an order reference or a voucher code in a payload.
- Call a model outside `llm.GatedLLMClient` (the OpenAI gate), or in a test.

## P97 T4 notes

- A version may name **targets** (giảm giá %, affiliate commission, ads budget / ROAS of several campaigns, a voucher over a product
  list): `multi.expand` makes one single-target version each; `shopee_recommendations.targets` adds the cards up (P50s add, range =
  root sum of squares of half-widths, an unknown profit stays unknown). `service.run_together` is "Chạy cùng nhau": it saves the ticked
  versions as cards (versions of the same change share a card) and hands them to `plans.run_together`.
- `combo` is Shopee's tiers form (`bundle_deal` + `tiers`, evaluated by `shopee_recommendations.bundle_tiers`); `listing_combo` is a new
  listing (`shopee_recommendations.listing_combo`). `ads` follows Shopee's edit form; keyword bids are not a lever.

## P98 W3-H: one result per option (ADR-122)

- Every evaluation (`service.evaluate_versions`, `choose`'s outcome, the P98 combo / KOL / ads builders) carries
  `result` = `OptionResult.json()` from **one** path, `engine_families.integrate`: the stored funnel of the scope
  (`funnel.base_from_rows` on the env's rows -- the env is loaded with `funnel=True`; shop for a shop-wide voucher or a
  minimum-spend gift, else the version's products) -> `engine_families.option_for` (+ `FamilyExtras`: the base's
  contribution rate and profit per order, combo pack evidence, ads history, KOL rates) -> `engine.run` with a seed
  hashed from the version's JSON (an all-point option runs one draw). `compare` lists the indexes / keys by
  per-30-day Δ lợi nhuận (`engine.compare`).
- `before_after.from_result` lays the seven rows out of `result.detail` and `outcome.result_delta` builds `delta`
  (and `per_day` / `period`) from the same columns; `driver` and `basis` read the result too. The card's money layer
  no longer produces a builder number (`before_after.build` is gone). The evaluators still
  give costs, floors, margins and profit per order (`cost`, `break_even`, `margin_*`, `details`).
- Several targets (`multi.SUM`): one result per `multi.expand`ed version, the version's result is their column-wise
  sum (`integrate.sum_results`); each target row carries its own `result` and its figures. One voucher over a product
  list (`multi.JOINT`) is one option on the union of the products.
- P100 B.15 (owner 2026-11-13): Ads edits of running campaigns (`kind = ads`, "Dịch vụ hiển thị" in Tự tạo phương
  án: create, compare and edit) are evaluated like every other kind -- So sánh, `choose` and `run_together` (the
  hide and its 422 `ads_edit_hidden` are gone). `integrate.ads_edit_result` builds `facts.AdsEditFacts` from the
  campaign's own history (`ads_history`, the Connector's campaign days on `CampaignSetting.days`, the per-product
  ads-report lines `product_ad_rows`, the products' on / off days, `RecoEnv.cancel_rate`) and
  `engine_families.ads_edit.ads_edit_option` turns the lever into an `OptionInput`:
  `budget` -- the new daily budget is the input; spend follows it only up to what the campaign spends when its
  budget does not hold it back (`measure.budget_state`: >= 95 % of the budget on most days = capped); a capped
  campaign spends the new budget (said as the maximum); `unlimited` on a capped campaign is not estimable.
  `roas` -- daily budget × `measure.spend_utilisation` at a similar target (`spend_utilisation_system` for
  Shopee-optimised), else cost (the unused budget) and break-even only. `remove_product` -- the campaign loses the
  product's share of spend / impressions / clicks / direct orders / GMV (its report lines); `add_product` -- the
  product's own past ad spend and CPA, capped by the unused budget; never advertised / capped campaign -> not
  estimable. Orders after = spend after ÷ the measured CPA. The result carries `ads` (`contract.AdsEvaluation`,
  wire `ads`): CPA now / after on direct ad orders × (1 − cancel rate), break-even CPA =
  `integrate.profit_per_order_before_ads` (the stored profit is after ads, so the ad spend per order is added back),
  verdict "có lãi" when CPA < break-even else "lỗ", profit after ads = ad orders × (break-even CPA − CPA), Shopee
  ROAS (ad GMV ÷ spend, placed orders) as reference. Δ total profit / ROI come from the engine on the INCREMENTAL
  orders only: Δ ad orders × `measure.incremental_share` (card orders per day with vs without ads ÷ ad orders per
  on-day), each worth the profit per order before ads, minus Δ spend (negative for a cut: the engine keeps a removal's
  views <= 0 and the build-up says "+ chi phí giảm"). No on / off history -> not estimable with the cost.
- `RecoEnv.cancel_rate` = 1 − confirmed ÷ placed orders of Tổng quan's `shop_overview` days that have both bases
  (`loaders.load_cancel_rate`, loaded with the env); None -> the ad orders stay placed orders and the card says so.
- P99: the `affiliate` kind (a commission rate, no KOL picked) has a result: cost = commission % × the product's
  expected Liên kết GMV (window GMV of its affiliate lines scaled to 30 days) + samples, break-even, extra orders
  "chưa ước tính được — đo sau lần gửi mẫu đầu" (measured per KOL only, through `/builder/kol/setup`).
- P99 `ads_new` (`specs.AdsNewSpec`): the Ads tab's new campaign as a version (`/builder/ads/setup` returns each
  setup's `spec`), saved through "Chọn" / "Chạy cùng nhau" as an `ads_new_campaign` card (certain layer = spend);
  its result is `integrate.ads_result`, seeded on the spec, so the tab, the card and Kế hoạch agree.
- P99 one base / margin / days: So sánh `today` is the versions' own scope (`integrate.scope_today`: the funnel
  base their results use, Luồng's margin `shop_profit.scope_margin_pct`); every version carries `today`; the
  picker's `margin_pct` and the card's `margin_before_pct` are that margin; a voucher without dates keeps the
  30-day horizon of its result (`inputs.days = 30`); Δ Đơn is rounded like `vn.count` (`wire.round_count`).
- ADR-122 d.13 in `engine_families`: E2 -- the reach to a voucher minimum / combo tier is the share of orders within
  20 % below it (a tier: at least one unit), measured with >= `MIN_REACH_ORDERS` orders, else the 0 / 20 / 50 % prior
  on those near orders (tagged prior); E3 -- a combo builder row of a pack size the product already has
  (`integrate.pack_sold_today`) only switches buyers (Δ Đơn 0); a new pack size adds orders from the matching
  variation (the product's CTR / CTOR, views × the variation's share of orders, AOV = the pack price).
- Ads on / off days come from the stored funnel's product Thẻ sản phẩm rows (`ads_spend` > 0 = on); product rows
  post ad GMV, not ad orders, so a day's ad orders are its ad GMV ÷ the day's card AOV.

## P99c (2026-11-10)

- The outcome's `cost` / `break_even` cover the version's own days (`result.days`, else the set
  dates, else 30): a money-layer figure for another period (combo / bundle / gift / Ads /
  Liên kết month, a 30-day break-even) is replaced by the result's `cost.total` /
  `cost.break_even_orders` / `break_even_aov` over those days (`source: "result"`, month-scaled
  parts such as `expected_units` dropped), or is null with `reason` `no_result_for_days`
  (`source: "none"` / `null`). Both blocks carry `period_days` = those days and `source`.
- So sánh (`compare`) ranks by Δ lợi nhuận (likely) per day of each version's own days, nulls
  (no result, unknown profit, unknown giá vốn) last; the response says so in `sort_basis`
  (`key` `delta_profit_per_day`, `label`, `detail`).

## P99b (owner 2026-11-10)

- A version's result covers exactly its set dates: `delta` / `cost` are for `result.days`; each
  evaluated version carries `dates` (`from`, `to`, `days`, `set`, `label`). `per_30d` is secondary
  (`secondary: true`, `label` "Quy đổi 30 ngày (tham khảo)"); since P99c it is no longer the sort key.
- The builder base (`load_env`) and the picker's 90 / 30-day views need the stored daily rows: a data
  day without its row raises `shopee_analytics.stored.RowsNotMaterialized` (409
  `rows_not_materialized`), never the raw tables' unspread split.
- Profit per order is unknown (`None`) when the base counts its days and no day with costs had an
  order -- never every order of the window.
