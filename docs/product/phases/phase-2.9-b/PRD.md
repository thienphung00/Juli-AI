# PRD: Phase 2.9-B — Fujiwa T1 Shop GMV Forecast Experiment

> **Canonical docs:** `EXECUTION.md` Phase 2.9-B brief · [ADR-032](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/032-fujiwa-t1-gmv-experiment-scope.md) (experiment scope) · [ADR-011](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/011-display-grade-analytics-layer.md) / `docs/ml/ml_layer.md` (T1 ETS locked; Prophet rejected) · [ADR-029](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/029-phase-2.9-analytics-historical-backfill.md) (shared analytics schema / A-36) · `CONTEXT.md` § GMV impact measurement · Partner contract A-36 in `docs/integrations/tiktok_api/contract-collection.md`.
>
> **Parent issue:** [#486](https://github.com/thienphung00/Juli-AI/issues/486) — filed via
> `to-prd` from grill-with-docs (2026-07-23).
>
> **Relationship to Phase 2.9:** Separate parent track (**2.9-B**). Phase 2.9 (backfill, #462) supplies warm A-36 history; 2.9-B **reads** that history and does **not** change backfill exit gates, ETL, or Partner call budgets.
>
> **Child slices:** to be filed via `to-issues` after this PRD is accepted.

## Objectives

1. **Prove T1 forecast quality on real Fujiwa data** — Fit a single display-grade **T1 ETS / Holt-Winters** model on daily shop GMV (Partner **A-36**, TikTok GMV — never Net Revenue) and measure holdout accuracy against a naive/mean baseline.
2. **Produce a rough shop-level incremental GMV view** — On the holdout window, emit observed vs counterfactual GMV (and derived incremental GMV / rate) with prediction intervals and an explicit **rough / short-history** `data_confidence` badge — calibration only, not decision-grade.
3. **Pathfind Phase 4 T1** — Exercise the locked ML-layer algorithm (`statsmodels` ETS + short-series fallback) on live analytics rows so Phase 4 can adopt or abandon with evidence.
4. **Keep the experiment disposable and honest** — Offline CLI, local artifacts only, soft quality bar (no promotion gate), no claim of Juli ROI, no Product/LIVE driver regression in this phase.
5. **Preserve forecasting package clarity** — Add shop-GMV forecasting as a **second, named model** beside existing inventory-depletion forecasting (separate APIs and result types).

## Problem Statement

Juli will eventually need to estimate how product work moves client GMV (mediated path: Juli → Product/LIVE metrics → GMV). That future stack needs a trustworthy **shop-GMV baseline/counterfactual** building block (T1). Phase 2.9 is loading Fujiwa Partner Analytics into the shared schema, but we have **never run T1 ETS on real shop GMV**, Prophet is **rejected** for short history (ADR-011), and shipping the full Incremental GMV v2 design (counterfactual + Product/LIVE driver regression) would be two models and premature attribution science.

We need a **focused Phase 2.9-B experiment**: one model, real Fujiwa A-36 series, clear quality readout, cheap to abandon — before investing in mediator elasticities or Juli→metric lift.

## Solution

Run **Phase 2.9-B** as a **separate parent track** parallel to Phase 2.9 completion:

- Read Fujiwa daily shop GMV from the **shared** analytics store populated by Phase 2.9 (A-36 revenue grain).
- Fit **one** T1-style **ETS / Holt-Winters** model (`statsmodels`) with catalog rules: weekly seasonality only when fit window has ≥ ~2 full weekly cycles; yearly seasonality **off**; if the fit series is too short/sparse for ETS, use the catalog **linear/mean short-series fallback** (still part of T1, not a second product model).
- Use **Design A** splits only: default **earliest ~70% fit / latest ~30% holdout** (CLI-overridable). **No** intervention date; **no** Product/LIVE or Juli launch-date research in this phase.
- Score holdout: **MAPE**, interval diagnostics, and **beats naive/mean baseline?** Soft bar only — beat-naive → eligible to explore hop 2 later; worse-than-naive → reconsider/abandon. **Not** a hard MAPE ≤ X% promotion gate.
- Write **local offline artifacts** only (`--output-dir`: daily + monthly tables as parquet/CSV, plus `metrics.json` with MAPE, baseline comparison, `data_confidence`, run metadata). Do **not** write product Supabase tables or `models/` promotion layout.
- House code in the existing forecasting package as an explicitly named **shop GMV** model alongside inventory depletion — separate public interfaces and result types; shared helpers only for generic series math.

Target-state **mediated Juli GMV impact** (Juli → mediator lift × matched Product/LIVE elasticities) and hop-2 regressions remain **documented follow-ons**, not 2.9-B must-haves.

## User Stories

1. As an ML engineer, I want a single T1 ETS shop-GMV experiment on Fujiwa, so that Phase 4 forecasting is grounded in real analytics history rather than synthetic parquet only.
2. As an ML engineer, I want Prophet explicitly forbidden for this experiment, so that we do not violate ADR-011 / `ml_layer.md` or invent false seasonality precision on ~4 months of data.
3. As an ML engineer, I want yearly seasonality disabled, so that ETS is not asked to learn cycles the series cannot support.
4. As an ML engineer, I want weekly seasonality enabled only when the fit window has at least ~2 full weekly cycles, so that seasonality is data-justified.
5. As an ML engineer, I want a linear/mean fallback when the fit window is too short/sparse for ETS, so that the experiment still runs and reports honest method metadata.
6. As an ML engineer, I want the fallback recorded as `method` / metadata on outputs, so that reviewers know whether ETS or fallback produced each run.
7. As a data scientist, I want Design A walk-forward/holdout (default ~70/30 earliest/latest), so that we measure forecast quality without inventing an intervention date.
8. As a data scientist, I want the fit/holdout ratio to be CLI-overridable, so that sensitivity checks are possible without code changes.
9. As a data scientist, I want holdout MAPE reported in `metrics.json`, so that quality is comparable across runs.
10. As a data scientist, I want a naive and/or mean baseline scored on the same holdout, so that “beats baseline” is an explicit soft gate.
11. As a data scientist, I want a clear boolean (or equivalent) `beats_naive_baseline` in metrics, so that go/no-go for exploring hop 2 later is visible.
12. As a product owner, I want all incremental-GMV figures tagged with `data_confidence` reflecting short history (e.g. rough — limited months), so that nobody treats outputs as decision-grade.
13. As a product owner, I want daily and monthly tables of observed_gmv, counterfactual_gmv, incremental_gmv, incremental_gmv_rate, forecast_lower_bound, forecast_upper_bound, so that calibration reviews have a complete series.
14. As a product owner, I want monthly rollups defined as sums (or documented aggregations) of daily GMV fields, so that monthly figures are consistent with Phase 2.9 revenue semantics.
15. As a backend engineer, I want the experiment to **read** Phase 2.9 shared analytics rows (A-36 shop GMV) and never trigger Partner API fetches, so that call budgets and backfill partitions stay untouched.
16. As a backend engineer, I want Fujiwa selected by explicit shop identifier (CLI/config), so that the job is parameterized for later shops even if exit is Fujiwa-only.
17. As a backend engineer, I want a clear error when A-36 daily coverage is insufficient for the chosen split, so that we fail fast instead of fitting garbage.
18. As a backend engineer, I want GMV treated as TikTok Partner GMV and never labeled Net Revenue, so that Main KPI language stays correct.
19. As a backend engineer, I want `statsmodels` added as a pinned dependency for the T1 path, so that ETS is reproducible in CI and local runs.
20. As an ML engineer, I want shop-GMV forecasting housed beside inventory depletion forecasting but with separate APIs and result types, so that `get_forecast`-style inventory calls cannot be confused with shop GMV counterfactuals.
21. As an ML engineer, I want inventory depletion behavior and tests to remain unchanged by this phase, so that intelligence-track stockout signals do not regress.
22. As a maintainer, I want MODULE / package documentation updated to list both forecast models (purpose, inputs, outputs, non-goals), so that future agents do not merge the two.
23. As an operator, I want an offline CLI that accepts shop id, output directory, and optional split overrides, so that the experiment is runnable after backfill without a product UI.
24. As an operator, I want artifacts written only under the chosen output directory (parquet and/or CSV + metrics.json), so that nothing lands in production Analytics tables or promoted model stores.
25. As a security-conscious engineer, I want no secrets in artifact files and no PII beyond shop-scoped analytics aggregates already stored, so that offline outputs are safe to share internally.
26. As a reviewer, I want unit tests on series loading contracts, split math, ETS/fallback selection rules, MAPE/baseline comparison, and artifact schema, so that behavior is locked without live Partner calls.
27. As a reviewer, I want fixture-based daily GMV series (not live DB required in CI), so that tests are deterministic.
28. As a product owner, I want this phase **not** to implement Product/LIVE driver regression, so that we do not ship hop 2 before T1 quality is judged.
29. As a product owner, I want this phase **not** to implement Juli→mediator lift, so that we do not claim Juli ROI from a forecast-quality experiment.
30. As a product owner, I want matched CTR–GMV grain and primary hop-2 pairs (A-34 product ctr→product gmv; A-29 LIVE click_through_rate→LIVE gmv) documented as **follow-ons** in this PRD, so that future work inherits the grill decisions without re-deriving them.
31. As a product owner, I want Inventory and Customer Support measurement and Value calculator tab changes out of scope, so that assumption-based planning figures are not mixed into this experiment.
32. As a program owner, I want Phase 2.9-B exit independent of Demo/Dashboard UI and of Phase 2.9 coverage reporter UI, so that ML pathfinding does not block frontend tracks.
33. As a program owner, I want Phase 2.9-B to declare a dependency on usable Fujiwa A-36 daily history from Phase 2.9, so that implementers know to wait for (or use) sufficient backfill coverage before claiming experiment results.
34. As an ML engineer, I want prediction intervals (or documented unavailable intervals under fallback) on counterfactual outputs, so that wide uncertainty is visible.
35. As an ML engineer, I want run metadata (fit date range, holdout date range, algorithm, seasonality flags, dependency versions) in metrics.json, so that runs are auditable.
36. As a data engineer, I want the loader to use shop-level A-36 overall GMV (not LIVE/VIDEO breakdown alone) as the primary series for this experiment, so that the headline matches shop GMV.
37. As a data engineer, I want optional diagnostic export of series length / missing days, so that coverage gaps explain poor MAPE.
38. As a future Phase 4 owner, I want this experiment explicitly labeled non-promoted / disposable, so that joblib promotion gates are not applied here by mistake.

## Implementation Decisions

### Modules (by responsibility)

1. **Shop GMV series loader** — Loads Fujiwa (shop-parameterized) daily shop GMV from shared analytics intervals for A-36 / revenue shop grain; validates continuity enough for the requested split; returns a dated series + coverage diagnostics. Read-only; no Partner calls.
2. **T1 shop GMV counterfactual engine** — Fits ETS/Holt-Winters per `ml_layer` T1 rules; applies short-series linear/mean fallback; produces point forecasts and intervals (or documents when intervals are unavailable); never uses Prophet.
3. **Holdout split + evaluator** — Applies Design A default ~70/30 (overridable); computes holdout MAPE; scores naive/mean baseline; sets soft `beats_naive_baseline` (or equivalent).
4. **Incremental GMV assembler** — Builds daily and monthly rows: observed, counterfactual, incremental, rate, bounds, `data_confidence`.
5. **Offline artifact writer** — Writes parquet/CSV tables + `metrics.json` under caller `--output-dir` only.
6. **Experiment CLI** — Operator entrypoint: shop id, output dir, optional split ratio / dates; prints summary metrics; exit non-zero on insufficient data or hard failures.
7. **Forecasting package documentation** — Multi-model index: inventory depletion vs shop GMV T1; separate public interfaces and result types.
8. **Dependency pin** — Add/pin `statsmodels` for the T1 path; keep inventory depletion free of that dependency if practical.

### Interfaces / contracts (behavioral)

- **Input:** Shop identifier; analytics DB/session or equivalent read path already used by backend; optional CLI overrides for fit fraction or explicit fit/holdout end dates.
- **Output artifacts (minimum):**
  - Daily table columns: date, observed_gmv, counterfactual_gmv, incremental_gmv, incremental_gmv_rate, forecast_lower_bound, forecast_upper_bound, data_confidence, method
  - Monthly table: month, same measures aggregated per documented rule, data_confidence
  - `metrics.json`: mape_holdout, baseline_mape (or equivalent), beats_naive_baseline, fit_range, holdout_range, seasonality_weekly, seasonality_yearly (always false), method, data_confidence, shop_id, series_days, missing_day_count
- **Errors:** Insufficient history for split; missing A-36 series; empty holdout; I/O failures on output dir — typed/clear messages, non-zero CLI exit.
- **Invariants:** No writes to analytics product tables; no `models/` promotion; no Partner API; GMV ≠ Net Revenue; inventory forecast API unchanged.

### Architectural decisions

- Separate parent phase **2.9-B** from Phase 2.9 backfill ([ADR-032](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/032-fujiwa-t1-gmv-experiment-scope.md)).
- Algorithm: T1 ETS per ADR-011 / `ml_layer.md`; Prophet rejected.
- Design A only — no intervention date for this ship.
- Soft quality bar only — not Phase 4 promotion thresholds.
- Multi-model forecasting package — shop GMV ≠ inventory depletion.
- Target-state mediated Juli impact and hop-2 matched elasticities are **follow-ons** (see Further Notes).

### Schema / API

- **No** required Alembic migrations for experiment outputs (local files only).
- **No** new seller-facing HTTP API required for exit.
- May reuse existing analytics read/repository patterns; must not couple training into backfill workers.

### Assumptions

- Phase 2.9 has produced (or will produce before meaningful experiment conclusions) usable Fujiwa daily A-36 GMV coverage for a multi-month window starting ~2026-03-16.
- Shared analytics interval rows expose shop-level daily GMV suitable for a single shop series (overall GMV).
- Operators can run the CLI with normal backend DB credentials used for analytics reads.
- ~4 months of history implies wide intervals and rough confidence — expected, not a defect by itself.

## Testing Decisions

- Prefer tests of **external behavior**: split boundaries, method selection (ETS vs fallback) given series length, MAPE/baseline comparison correctness, artifact schema/columns present, CLI insufficient-data failure, inventory forecast tests still pass unchanged.
- Test modules: series loader (fixture rows), counterfactual engine, evaluator, artifact writer, CLI argument/validation behavior.
- Prior art: `tests/unit/test_forecasting.py` (inventory depletion), AI dataset CLI/parquet tests, analytics interval contracts — extend patterns; do not require live Partner or live Supabase in CI.
- Use synthetic daily GMV fixtures with known MAPE properties where helpful.
- Do not require promotion-gate / joblib artifact tests for this experiment.

## Out of Scope

- Product/LIVE driver regression (hop 2) and Juli→mediator lift (hop 1).
- Intervention-date / launch-date causal design (Design B).
- Prophet, LightGBM/LightFM, RandomForest for this experiment.
- Inventory or Customer Support measurement; Value calculator Inventory/CS tab changes.
- Writing results to product Supabase Analytics tables or `models/` promotion layout.
- Demo/Dashboard UI, seller-facing charts, copy-layer wiring.
- Phase 2.9 backfill ETL, Partner call budget, coverage reporter exit gate changes.
- A-33 impressions fan-out; Ads/Marketing metrics.
- Claiming Juli ROI or decision-grade attribution.
- Hard MAPE promotion threshold for Phase 4 artifact load.
- Multi-shop exit (parameterize shop id; Fujiwa is the experiment shop).

## Further Notes

### Target-state follow-ons (not 2.9-B must-haves)

After T1 quality is judged usable (soft bar):

1. **Hop 2 — matched elasticities:** A-34 product `ctr` → product `gmv`; A-29 daily LIVE `click_through_rate` → LIVE `gmv`; compose to shop; A-36 as sanity check only (A-36 has shop GMV but **no shop CTR**).
2. **Hop 1 — Juli → mediator lift:** vs no-Juli baseline trends on those mediators once workflows are shipped.
3. **Mediated Juli GMV impact:** compose hop 1 × hop 2; still calibration-grade until promotion gates exist.

### Risks

- Short history → high MAPE even when ETS is correctly implemented; soft bar may fail honestly.
- Sparse/missing A-36 days → fallback or abort; coverage diagnostics must be visible.
- Confusing inventory `ForecastResult` with shop GMV outputs if package separation is weak — mitigate with separate types/APIs and docs.
- Running before backfill coverage is ready → meaningless metrics; declare dependency explicitly in slices.

### Observability / rollout

- CLI prints summary metrics; artifacts are the record of run.
- Operator-triggered offline runs only; no Celery beat / scheduler requirement.
- Recalibrate/re-run as more A-36 history accumulates; do not treat one run as permanent truth.

### Exit gate

- [ ] Shop-parameterized offline CLI runs on Fujiwa A-36 daily GMV without Partner calls
- [ ] T1 ETS (+ documented short-series fallback) implemented; Prophet absent
- [ ] Design A default ~70/30 holdout; overrides documented
- [ ] Artifacts: daily + monthly tables + `metrics.json` with MAPE, baseline comparison, `data_confidence`, run metadata
- [ ] Soft quality bar reported (no hard promotion gate)
- [ ] Inventory depletion forecasting behavior/tests unchanged; package docs list both models
- [ ] No product DB writes; no Value calculator / hop-1 / hop-2 implementation
- [ ] Unit tests with fixtures pass in CI without live Partner

## Assumptions (filing)

- Grill locks in ADR-032 / CONTEXT.md are authoritative for this PRD.
- Phase naming **2.9-B** denotes a sibling parent to Phase 2.9 backfill, not a child issue of #462 unless product later links them for tracking only.
- `to-issues` will decompose this parent into independently grabbable slices after acceptance.
