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
| `listing` | the listing family's pure core: title audit (missing / late / > 120 chars), deterministic title rewrite from the shop's own words + core keywords, keyword promotion within five "Chính", unit price |
| `refs` | `attach_card_refs`: `card {id, family, title, at_stake_per_month}` on the analytics payloads (seller: published cards; Ops: drafts too) |
| `ranking` | contract 11: hard filters, gap-share score at P25, fallback dGMV/tháng, "đáng thử" slot |
| `learning`, `impact`, `measure` | calibration, coverage, acceptance statistics; ADR-077 ratio-form DiD; readings at the plan end and the natural-experiment backfill |
| `sim_priors` | the `juli-sim/priors/v1` loader (schema: `~/juli-sim-pilot/funnel/README.md`) |
| `store`, `service`, `stale` | persistence, use cases, staleness |

## Listing family (contract 8: Lượt xem / CTR)

`title`, `keyword`, `cover_image`, `price_display` are traffic levers: no certain layer (the card
says so), a predicted range from the lift model on views / CTR over the product's search or
Thẻ sản phẩm GMV. A title never exceeds 120 characters and never holds a seller banned term or a
generic claim pattern (`content_cards.guardrails.check_banned`). Read-back: `title` through
`platform_items.name`; `cover_image` / `price_display` through the cover URL changing
(`expected = {"image_urls": {"changed_from": [url]}}`, `card_events/verification`); `keyword`
lives in Juli's own key list and has no read-back. A cover or price card needs the snapshot's
cover URL; a keyword card needs the market volumes the owner uploads.

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
