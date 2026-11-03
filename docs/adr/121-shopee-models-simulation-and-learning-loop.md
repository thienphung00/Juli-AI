# ADR-121: Juli's models and the buyer simulation in the Shopee recommendation loop

**Status:** Accepted (owner, 2026-11-03, grill D83)
**Date:** 2026-11-03
**Deciders:** owner (Thiên) with the agent.

**Builds on:** [ADR-077](077-incremental-impact-measurement.md) (impact reading),
[ADR-107](107-card-journey-log-and-measurement-plan.md) (card log, pre-registered plan, pooled effects),
[ADR-114](114-seller-consented-randomized-experiments.md) (experiments),
[ADR-115](115-point-in-time-training-data-and-per-shop-model-gate.md) (model gate),
[ADR-116](116-client-data-lanes-consent-and-model-split.md) (lanes, client layer, no pooling),
[ADR-120](120-shopee-precise-shop-view-profit-floor-and-sources.md) (the Shopee shop view).
Contract: `fasttrack/contracts/p90-metrics.md` §8 (wiring), §11 (ranking).

## Context

ADR-120 defines what is shown and computed exactly (fees, profit, floor, what-if "chắc chắn"). This ADR
defines where models and the local buyer simulation (`~/juli-sim-pilot`, D35–D37, D45, D61) enter:
detection, candidate screening, the predicted range ("dự kiến"), ranking — and how every executed
recommendation and its measured outcome refines them. Constraints: ORY has ~4 orders/day (most single
cards are "khó kết luận" under ADR-107 §7); ORY holds no `pooled_training` consent and Shopee ToS
§6.2(c) forbids pooled seller aggregates; the simulation did not beat its baseline on ORY's one test
(sim-pilot findings ledger E7).

## Decisions

1. **Roles.**
   - *Flow baseline* (`services/shopee_kpi/flow_glm.py`): the normal band that decides "critical"
     (ADR-120 d.6) and the counterfactual for measurement; sale days modelled, not alarmed on.
   - *Rules + profit package*: candidate actions per critical metric (contract §8) and the certain layer.
   - *Lift model* (`services/optimize_product/prediction.py`, ported to Shopee change kinds): the
     predicted range of the target metric, converted to ΔGMV / Δprofit per month (P10–P90) through the
     GMV identity and `services/shopee_profit/`.
   - *Buyer simulation*: a **prior and a pre-screen only** — never the seller-facing outcome by itself.
   The seller sees ranges and results, never the model or method (ADR-116 as clarified 03/11).
2. **Ranking** = contract §11: hard filters (Δprofit ≥ 0 at P50, no SKU below its operating floor, spend
   within the daily cap, one change per product per window, in stock), then the share of the gap to the
   month's targets closed at P25, weighted to the furthest-behind KPI; no targets → ΔGMV/tháng at P25.
   Ops may reserve one slot for the simulation's "đáng thử" pick (largest expected learning among
   eligible actions).
3. **Frozen at proposal** (`card_events.proposed`): inputs, certain numbers, the lift model's range and
   version, the simulation run id and its prediction, the ADR-107 measurement plan.
4. **Learning loop.** At the final reading (14 / 28 days, ADR-077 vs the flow-baseline counterfactual):
   - lift-model calibration per (change_kind, metric): measured ÷ predicted, inverse-variance pooled
     within the shop, shrunk to the prior (`MIN_SHOP_RESULTS = 5`, `K = 5`);
   - coverage scored (share of results inside the predicted range) → ranges widened or narrowed;
   - simulation scored the same way and re-weighted (`funnel/reweight.py`); **per change_kind gate**: a
     simulation prior that does not beat the plain prior gets weight 0 for that change_kind;
   - executed-change days are marked so the flow baseline does not learn them as normal (ADR-114 view);
   - approve / dismiss reasons / expiry / `whatif_adjusted` feed **acceptance statistics** (ranking and
     default slider values) — never evidence that an action works.
   Stacked changes on one product in one window are measured as one bundle or excluded from calibration.
5. **Bootstrapping ORY.** ORY's past changes — the Shopee ad change log (`ops_log_*.csv`) and 12 months
   of voucher history — are scored once as natural experiments to give the first ORY calibration.
6. **No pooled forecasts.** ORY's lift calibration and forecasts learn from ORY only plus public priors
   (ADR-116 client layer); ORY's results never enter a forecast or lift model used for other shops, and
   vice versa. Exception by ORY's own consent (01/11/2026): the shared buyer simulation may be calibrated
   with ORY's Seller Centre product numbers (data set `ory_sc_sim_calibration`). New model versions for a shop pass ADR-115 offline →
   shadow → rollout → rollback; until then the rules path ranks live cards.
7. **Buyer simulation — where it is used.**
   | Design part | Use | KPI |
   |---|---|---|
   | Phân tích (Ops first) | segment × funnel-step drop-off as a labelled hypothesis for a critical metric | CTR, CTOR |
   | Candidate pre-screen | variants (title, cover, pack size, combo, voucher threshold) through the token-free funnel + `juli_rules`; drop those predicted worse than the current listing | CTR, CTOR, AOV |
   | Keywords | per core keyword (max 5, ADR-120 d.11): search-context card win rate vs that keyword's competitors, with volume and rank → title placement | search views, CTR |
   | Combos / packs | quantity model (nested logit, pack offset) → AOV / units for sets, thresholds, gift vs voucher | AOV, orders |
   | Voucher what-if | segment shares → prior for usage rate u and extra orders until ORY has its own voucher results | CTOR, orders |
   | Expected outcome | simulated effect (median, 90 % range) per product × change_kind = the lift model's prior | all |
   | Ranking | "đáng thử" pick (knowledge gradient) | — |
   Not used for impressions (an input to the simulation) or for margin (the profit package converts
   simulated volume into money).
8. **Boundary.** The simulation stays local (not a git repo; shop data and results never enter the
   repo). It exports a versioned file per run (`juli-sim/priors/v1`, modelled on `next_tests/v1`): per
   product × change_kind × segment the predicted relative effect {med, lo90, hi90}, the knowledge-gradient
   value and the run id. An Ops import (audited) writes it to a run table; the prediction service reads it
   as a weighted prior. Paid LLM runs (`sim.py`) need the owner's explicit approval and cost estimate.
9. **Consent scope.** ORY's Seller Centre numbers may calibrate the shared simulation (ORY, 01/11) **and ORY's
   own forecasts** (client layer, `service` consent; owner 03/11, no re-verification), never a pooled forecast /
   lift model — `juli-client-ops/clients/ory/compliance/data_register.md`, section 03/11/2026.
10. **Order (after the P90 field spec is approved):** (1) port the funnel to Shopee (search / discovery
    contexts, Shopee card elements, ORY competitors per core keyword, ORY segment shares from
    `sales_composition`) and validate on ORY's frozen Sep–Oct months; (2) export format + Ops import;
    (3) simulation priors in the lift model with the per-change_kind gate; (4) Phân tích segment cause
    (Ops only); (5) the "đáng thử" slot.

## Consequences

- New: Shopee lift-model port, prediction freeze, Shopee impact reader, calibration and coverage jobs,
  acceptance statistics, simulation import table, natural-experiment backfill for ORY.
- Seller copy never names a model, the simulation or personas; "dự kiến" ranges only.
- Until calibration exists, ranges are wide and labelled; single ORY cards will often read "khó kết luận".

## Alternatives rejected

- **Simulation output as the expected outcome** — not validated on ORY (E7); it is a prior, gated.
- **Pooling ORY with other shops** — no consent; Shopee ToS §6.2(c).
- **Learning from approvals as if they were effects** — acceptance is not impact.
