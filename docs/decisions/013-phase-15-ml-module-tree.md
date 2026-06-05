# ADR 013: Phase 1.5 ML Module Tree

## Status
Accepted

## Context

Phase 1.5 requires offline ML training (seller stage, buyer-behavior anomaly,
ad performance) with no production inference and no TikTok API calls. Legacy
`src/modules/catalog/domain/intelligence/scoring/` targets creator/livestream
signals and is slated for removal — seller-money ML must not extend it.

EXECUTION.md slice P1.5-1 bootstraps a dedicated Python module tree with
MODULE.md per `map.md`, pinned ML dependencies, and runner-agnostic dataset
assembly producing versioned parquet under `backtest/`.

## Decision

- **We will:** Add Phase 1.5 ML code under `src/modules/ml/` with one MODULE.md
  per deployable sub-module (`dataset`, `features`, `seller_stage`, `anomaly`,
  `ad_performance`, `artifacts` — added incrementally per issue).
- **We will:** Pin `pandas`, `pyarrow`, `scikit-learn`, and `xgboost` in
  `requirements.txt` at first ML touch (#136).
- **We will:** Expose plain Python functions and CLI entrypoints — no Celery,
  no scheduler coupling — so Phase 2 swaps the runner without rewriting ML logic.
- **We will not:** Extend legacy `intelligence/scoring` for seller-money models.

## Rationale

- Isolates offline ML from FastAPI ingestion paths and deprecated intelligence code.
- `map.md` tier-2 MODULE.md policy keeps new surfaces discoverable for `focus` and `review`.
- Runner-agnostic interfaces match Phase 2 daily batch design in `system-design.md`.

## Consequences

- `docs/architecture/map.md` gains `src/modules/ml/dataset` in #136; subsequent
  P1.5 issues add sibling rows without reshaping `src/apps` or `src/modules/ordering`.
- CI architectural-change gate requires this ADR when `map.md` is updated.
- Feature builders and trainers (#137–#140) depend on the dataset manifest contract
  established in #136.
