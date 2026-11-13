# backend/src/juli_backend/services/shopee_recommendations

## Purpose

P90 step 8 (ADR-121, `fasttrack/contracts/p90-metrics.md` sections 8, 11, 12): the Shopee
recommendation cards. Generators per family on top of `services/shopee_analytics` (critical
list, product pages, floors) and `services/shopee_profit` (the certain layer), ranking, the
predicted range, the learning loop, the simulation priors. Shape copied from `services/agent_runs`:
a service package behind a thin route (`api/routes/demo_shopee_recommendations.py`,
`api/routes/ops_shopee_recommendations.py`).

## Layers

| Module | Role |
|---|---|
| `kinds` | families, change kinds, section 8 wiring (`WIRING`), ADR-118 proposal kind, read-back kind, simulation kind, Seller Centre page, sliders |
| `env`, `loader` | `RecoEnv`: the analytics `PeriodView` of the last 30 days + live ads / voucher settings, locks, calibration, acceptance, simulation. `loader.load_env` is the only reader |
| `evaluate` | the certain layer per family, all arithmetic from `shopee_profit` (`voucher_whatif`, `price_change_whatif`, `profit_lines`, `five_numbers`, floors) |
| `generators` | candidates per family, driven by the critical list + an opportunity pass; fitted to the floors |
| `mega` | `mega_sale`: children re-priced ONCE on the same orders, one lever per line, floors across the stack, one cap; `fit_children` |
| `prediction` | lift = preset prior x calibration factor (shop evidence shrunk, `MIN_SHOP_RESULTS` 5, `K` 5) x coverage scale; simulation prior weighted by its gate; lift -> dGMV / dprofit P10-P90 |
| `plan` | ADR-107 measurement plan: MDE (alpha 5 %, power 80 %) -> 14 / 28 days / "khó kết luận" |
| `sheet` | execution sheet and the `change = {change_kind, target, expected}` the `executed` event carries (`card_events/verification.py`) |
| `cards` | one card = the frozen proposal payload |
| `listing` | the listing family's pure core: title audit (missing / late / > 100 chars), deterministic title rewrite from the shop's own words + core keywords, keyword promotion within five "Chính", unit price |
| `refs` | `attach_card_refs`: `card {id, family, title, at_stake_per_month}` on the analytics payloads (seller: published cards; Ops: drafts too) |
| `ranking` | contract 11: hard filters, gap-share score at P25, fallback dGMV/tháng, "đáng thử" slot |
| `learning`, `impact`, `measure` | calibration, coverage, acceptance statistics; ADR-077 ratio-form DiD; readings at the plan end and the natural-experiment backfill |
| `sim_priors` | the `juli-sim/priors/v1` loader (schema: `~/juli-sim-pilot/funnel/README.md`) |
| `fill_queue` | P97 D85.6: `enqueue_for_approval` queues `shopee_fill_jobs` (migration 124) for an approved card version; `jobs_for_shop` / `report` serve the Connector (token's shop only); `captured_ref_of` feeds `mark_executed`. Kill switch `CONNECTOR_FILL_LISTING`. Combo is not queued (TODO, T4's tier spec) |
| `product_queue` | P91 D-1: the per-product queue of open cards (`shop_proposals.product_queue`), pure `assign`, `requeue_products` / `requeue_shop`, `measuring` (`product_measuring`) |
| `versions` | P91 D-2: 2-4 versions per card; `ALTERNATIVES` = the one place that says which inputs per change_kind |
| `codes` | P91 D-5: `JC-<yymm>-<seq4>`, per-shop counter, `backfill_codes` |
| `store`, `service`, `stale` | persistence, use cases, staleness |

## Listing family (contract 8: Lượt xem / CTR)

`title`, `keyword`, `cover_image`, `price_display` are traffic levers: no certain layer (the card
says so), a predicted range from the lift model on views / CTR over the product's search or
Thẻ sản phẩm GMV. A title never exceeds 100 characters (P91 D-4) and never holds a seller banned term or a
generic claim pattern (`content_cards.guardrails.check_banned`). Read-back: `title` through
`platform_items.name`; `cover_image` / `price_display` through the cover URL changing
(`expected = {"image_urls": {"changed_from": [url]}}`, `card_events/verification`); `keyword`
lives in Juli's own key list and has no read-back. A cover or price card needs the snapshot's
cover URL; a keyword card needs the market volumes the owner uploads.

### P91 D-13: description, variations, hide, relist (and the import)

`description_first_line`, `variation_restructure`, `listing_hide`, `listing_relist` join the listing
family. Only the description has a prior (small, on CTOR); the others say "Không ước tính". The
sheet carries the product's own edit page (`page.item_deep_link`, shape not recon-verified, flagged),
`dependencies` (`depends_on` refs), `downloads` (cover image, https only) and the read-back kinds:
`listing_status` (item snapshot `unlisted`), `variations` (catalogue rows still listed + their newest
snapshot, an expected row names only the fields it fixes), `description_first_line` (no Connector
reader exists yet: `verification.DESCRIPTION_READBACK_ACTIVE = False`, the person confirms by hand).
An `executed` event with `payload.readback = False` is never read back (an imported, backdated
execution). `services/planned_changes` imports a list of these changes from an `.xlsx`
(`rows` = columns, parsing, checks; `importer` = preview / apply / versions); each valid row is a
`manual.create_manual(origin="import")` card with `external_ref`; tables in migration 120.
`fill.py` is the server half of the Connector's fill-in (`GET /v1/ingest/fill/{code}`, off unless
`CONNECTOR_FILL_LISTING`): the approved text, never a write.

## Persistence (ADR-118 reused, migration 115 for the rest)

A card is **one id** in three rows: `action_cards` (status `shopee_reco`, so the TikTok Decision
feed, which reads `active`, never shows it), `shop_proposals` (+ approvals / executions) and a
`proposed` event in `card_events` whose payload freezes inputs, certain numbers, the predicted
range and model version, the simulation run, the measurement plan and the execution sheet.
Migration 115 adds only `shopee_sim_prior_runs` and `shopee_reco_calibrations` (tenant-direct, RLS).

Status: `draft` (Ops) -> `sent` (Ops publishes) -> `approved` / `changes_requested` / `rejected`
(the client in Demo) -> `executed` ("Đã làm") -> measured. Events: `proposed`, `whatif_adjusted`,
`accepted` (carries the final inputs when the client moved them), `edited` (request a change),
`dismissed` (ADR-107 reason), `expired` (7 days), `executed` (one per change in the sheet, with
`change`), `impact_preliminary` (T+7, never calibrates), `impact_final`; `verified` / `mismatch` / `not_seen` come from the Connector read-back.

## P91: all cards, versions, codes

- Ranking keeps every card that passes the other hard filters; `duplicate_product` is the queue.
  Quyết định (`list_cards` default) shows `product_queue` 1 per product; `product_id=` / `queue=all`
  return all. A card leaves the queue at once when dismissed, withdrawn, expired, superseded or
  executed (a `planned` card, D-6, too); `product_measuring = {until, change_set}` says a running
  measurement is still open on the product. Every status path calls `requeue_products`;
  `requeue_shop` is the idempotent entry for the beat / measurement job.
- `card["versions"]`: version 1 = default (the only ranked one); refused / floor-breaching ones are
  kept and marked. What-if takes `version`; approve takes `chosen_version` (snapshot + events).
- Codes are assigned in `store.save_card`; `service.card_by_code` is the read for the later export.

## KOL cards (P91 D-9, D-11)

`kol_cards`: `affiliate_sample` "Gửi mẫu cho KOL" (creators with a sample on record) and
`affiliate_invite` "Mời KOL" (none yet), one card per creator, at most 8 per run. Version 1 = the
product with the best expected profit per sample; the other versions pitch the next products
(`kol_cards.product_alternatives`, hooked in `versions._alternative_candidates`) and move the sample
count / rate (`versions.ALTERNATIVES`). What-if: `item_id`, `qty`, `commission_pct`. Expected orders
come from the creator's clicks and conversion, the product's affiliate conversion and the channel
fit, shrunk toward the shop average with weight n / (n + 10) while the pair has few orders, with a wide
range below 10 orders ("Ít dữ liệu"); the formulas are in the module docstring. `cards.build_card`
hands these kinds to `kol_cards.build_kol_card` (same payload keys plus `card["kol"]`); the evaluator
`eval_kol` serves `evaluate`. Measurement scope = `card["kol"]["measurement"]` (KOL x product pair,
orders before / after the send date; series `shopee_analytics.kol.pair_daily`). Never a mega_sale child.

## P92 additions

- `combo_multi` takes 2-6 products; `add_on` 1-5 add-ons (price or % off, per-order limit, attach rate
  that pays the discount back); `gift` is a listing or a typed-cost "quà không bán" with a buy-X /
  min-spend trigger; `product_discount` / `price` / `flash_sale` take per-variation rows
  (`inputs.variations = [{sku, discount_pct | final_price | new_price_pct}]`); `ads_keywords` lists
  keywords + bids with no invented lift. `unit_cost` reads the seller's giá vốn / pack / VAT straight
  from the rules ("chưa tính" when none). `env.response_by_item` / `response_shop` let
  `prediction.predict_lift` use the product's own response to a price cut (`Lift.source`
  `product_history` / `shop_products`). `env.excluded` drops excluded listings from `item_ids`, the
  generators and `manual.build_variant`. The builder that drives all of this is `services/shopee_builder`.

## Rules

- Certain ("chắc chắn") is arithmetic on the shop's real orders; predicted ("dự kiến") is a
  range. Number 2 of the five is never taken from a certain layer without volume.
- Ads are labelled "đơn đã đặt" and never mixed into confirmed totals.
- Gate weight 0 leaves every range byte-identical to the no-simulation path (tested).
- Acceptance statistics (approve / dismiss / expire / what-if) move slider defaults and break
  ranking ties only; `prediction` has no path to them.
- A stacked / `mega_sale` change is measured as one bundle and excluded from per-kind calibration;
  a reading without a control series (tier Thấp) is kept but feeds neither factor nor coverage.
- No client value in the repo: the simulation file and every report are counts / hashes.

## Staleness hook for the seller import (Step 4)

`stale.mark_stale_for(session, shop_id, product_ids=None, sku_ids=None, *, shop_wide=False)` flags
open cards (`draft` / `sent` / `changes_requested` / `approved`) whose products or SKUs changed
(`"item"` or `"item:variation"` ids both match), or, `shop_wide=True` (margin target / marketing
cap), every card of a target-sensitive family. It returns the number flagged and writes only
`action_cards.metadata_json`. Importing this package registers `stale.on_stale_request` with
`shop_inputs.register_recompute_hook`, so `shop_inputs.mark_stale` calls it. `rerun_stale` then
recomputes only the flagged cards (draft: replaced; sent / changes_requested: ADR-118 `revise`,
the client's text is never edited; approved: kept and left flagged for a person).

## Must not

- Write to Seller Centre of any kind (assisted execution only).
- Read rules except through `services/shopee_analytics` (`load_context`, `rules.for_month`).
- Re-derive a number `shopee_profit` already computes.
- Put a key starting with `buyer`, an order ref or a voucher code in a payload.

## P97 T4 additions

| Module | Role |
|---|---|
| `targets` | one card, many targets (D85.13): merges single-target cards (money, floors, spend), `targets` + `fill` on the payload |
| `bundle_tiers` | `bundle_deal` over a product list with tiers "Mua N" (D85.15) |
| `listing_combo` | a new listing that sells existing products together (D85.16) |
| `plan_groups` | groups of a plan (D85.14, P94): placing versions, exclusive fields, periods, entries, export rows / `.xlsx` |
| `fill_queue_port` | the single call into T3's fill queue (`enqueue_for_approval`); a stub until `fill_queue` exists |

## month_plan (P100 canvas)

`month_plan.month_plans` / `month_plan` is the ONE computation of Kế hoạch's month figures (goal_gmv,
goal_profit, baseline_*, uplift_*, mtd_*, day, days_in_month) for scope `running` (executed plans) or
`running+draft`. Tổng quan's month card (`channel_split._plan_block`, scope running) and the Kế hoạch screen
(`GET /plan` answer's `month`, both scopes) read only this. Rules are in the module docstring.
