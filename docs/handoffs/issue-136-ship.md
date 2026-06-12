# Handoff: ship complete — Issue #136

## Shipped

- Issue #136 closed
- PR #144 merged — commit `efd720d`

## What shipped

- `src/modules/ml/dataset` — synthetic parquet generator, schema validation, manifest output
- CLI: `python -m src.modules.ml.dataset.cli` (`assemble-backtest-dataset`)
- Pinned ML deps: `pandas`, `pyarrow`, `scikit-learn`, `xgboost`
- ADR-013 + `map.md` registration for Phase 1.5 ML module tree
- 9 integration tests covering all acceptance criteria

## Rollback

```bash
git revert efd720d
```

No migrations or runtime config. Remove ML deps from `requirements.txt` only if rolling back the entire Phase 1.5 tree.

## Follow-up work

- **#137** — Feature builder for all three model suites (blocked by: none — #136 complete)
- **#138–#140** — Model trainers (blocked by: #137)
