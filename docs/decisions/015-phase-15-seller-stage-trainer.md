# ADR 015: Phase 1.5 Seller Stage Trainer Module

## Status
Accepted

## Context

Issue #138 adds the seller lifecycle classifier trainer between the shared feature
builder (#137) and model artifact serialization (#141). The trainer must:

- Train on backtest features from `build_seller_stage_features`
- Port Phase 1 rules baseline from `web/src/lib/seller-stage-router/` for comparison
- Expose stable inference (stage + confidence) and rules-vs-ML comparison report
- Remain offline — no TikTok API calls, no UI changes, no Postgres writes

`docs/architecture/map.md` gains a new tier-2 module row for `src/modules/ml/seller_stage`.

## Decision

- **We will:** Add `src/modules/ml/seller_stage` with `classify_seller_stage` (rules baseline),
  `train_seller_stage`, `predict_seller_stage`, and `compare_to_rules_baseline`.
- **We will:** Use `RandomForestClassifier(class_weight="balanced")` with fixed random seed
  for reproducible training on rules-derived labels from shop feature rows.
- **We will:** Write `metrics.json` and `training_log.json` via CLI `train-seller-stage`.
- **We will not:** Serialize joblib artifacts (#141), train anomaly/ad models (#139–#140),
  or modify the Phase 1 web router.

## Rationale

- Rules baseline is authoritative Phase 1 ground truth; Python port enables offline
  backtest comparison without coupling training to the Next.js app.
- Rules-derived labels bootstrap training when seller-stage labels are absent from parquet.
- Disjoint module boundary allows parallel work on #139 and #140 per `issue-workflow.mdc`.

## Consequences

- `map.md` registers `src/modules/ml/seller_stage`; #141 consumes trained models for serialization.
- Golden boundary fixtures mirror `boundary-fixtures.ts` for cross-language QA parity.
- Phase 2 inference loads serialized artifacts from #141, not this training module directly.
