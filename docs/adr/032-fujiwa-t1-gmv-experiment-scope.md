# ADR 032: Fujiwa T1 GMV experiment — single ETS model, defer driver regression

## Status
Accepted

## Context

We want an early, disposable signal on whether shop-GMV forecasting quality is
good enough to support later “Juli → client GMV impact” measurement (after
end-to-end workflows ship; Phase 4 ML pipeline or sooner). The Incremental GMV
Attribution Pipeline Design v2 proposed both a shop-GMV counterfactual (Prophet)
and a Product/LIVE driver regression. That is two models; Prophet is already
rejected for bounded history by ADR-011 / `ml_layer.md`. Phase 2.9 is backfilling
Fujiwa Partner Analytics into the shared Supabase schema (ADR-029) — the natural
input for an offline experiment.

Alternatives: (a) ship v2’s full two-stage stack now; (b) one sklearn Product/LIVE
driver model only; (c) one T1 ETS forecaster on shop GMV only; (d) wait for Phase 4.

## Decision

- We will: Run a **Fujiwa T1 GMV experiment** — a single **T1-style `statsmodels`
  ETS / Holt-Winters** model on daily shop GMV (A-36), with the catalog’s
  short-series linear/mean fallback as part of T1 (not a second model).
- We will: Use **Design A** for the split — walk-forward / holdout on A-36 only
  to judge forecast quality and rough observed−counterfactual on the holdout.
  Default **~70% earliest fit / ~30% latest holdout** (CLI-overridable).
  **No** intervention date; **no** parallel Product/LIVE or Juli launch-date
  research for this experiment.
- We will: Judge quality with a **soft bar** — report holdout MAPE and whether
  ETS beats a naive/mean baseline; **not** a hard MAPE ≤ X% promotion gate.
  Worse-than-naive → reconsider or abandon; beat-naive → eligible to explore hop 2
  later.
- We will: House that experiment under **`juli_backend.ai.forecasting`** as a
  second, explicitly named **`shop_gmv`** model alongside inventory depletion —
  separate modules, APIs, and result types; shared helpers only for generic
  series math. Do not overload inventory `ForecastResult` / `get_forecast`.
- We will: Treat outputs as **rough calibration** (wide intervals,
  `data_confidence` badge); not a promoted decision-grade artifact. Persist only
  to a local CLI `--output-dir` (parquet/CSV + `metrics.json`) — **not** product
  Supabase tables, **not** `models/` promotion layout.
- We will: **Defer** Product/LIVE driver regression until forecast quality on
  this experiment is judged usable. That regression is the planned **second hop**
  of **mediated Juli GMV impact** (mediators → GMV), not Juli impact alone.
- We will not: Use Prophet; implement Inventory/Customer Support measurement;
  wire Value calculator Inventory/CS tabs; claim experiment ΔGMV as Juli ROI;
  implement the Juli→mediator hop in this experiment; train models inside
  Phase 2.9 backfill/ETL; invent or research an intervention date for this ship;
  write experiment results into live Analytics/product DB tables.

## Consequences

- Early Phase 4 pathfinder for T1 on real Fujiwa history; cheap to abandon.
- No Product/LIVE share-of-ΔGMV story in this experiment — only total
  observed-vs-counterfactual shop incremental GMV.
- Target-state **mediated Juli GMV impact** = (Juli → Product/LIVE mediator
  lift) × (Product/LIVE driver regression elasticities). This experiment
  validates forecasting building blocks for baselines; it does not ship either
  hop yet.
- Target-state hop 2 (deferred): **two parallel matched elasticities** —
  A-34 product `ctr`→product `gmv` and A-29 daily LIVE `click_through_rate`→LIVE
  `gmv` — composed to shop level; A-36 is sanity check only (no shop CTR).
- Code home: `ai/forecasting/shop_gmv/` (name TBD at implement) next to inventory
  depletion — multi-model package, clear separation.
- Split: Design A walk-forward/holdout only; no intervention date for this ship.
- Quality: soft bar (holdout MAPE + beat naive/mean); no hard promotion gate.
- Outputs: local `--output-dir` artifacts only (no product DB / models promotion).
