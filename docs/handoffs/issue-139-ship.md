# Handoff: ship complete — Issue #139

## Shipped

- Issue #139 closed
- PR #147 merged — commit `9158298`

## What shipped

- `src/modules/ml/anomaly` — `train_anomaly`, `predict_anomaly`, `build_anomaly_training_frame`
- Training on `labels.parquet` joined to Group A buyer×shop features (ADR-011 scope)
- Per-class precision/recall for `item_swap` and `empty_return` in `metrics.json`
- Inference schema: `{ anomaly_class, confidence, feature_summary, is_anomaly }`
- CLI `train-anomaly` writes metrics + training log JSON
- ADR-016 documenting the anomaly trainer module
- 7 AC-mapped tests in `tests/unit/test_anomaly_trainer.py`

## Rollback

```bash
git revert 9158298
```

No migrations or runtime config.

## Follow-up work

- **#140** — Ad performance analyzer trainer (parallel)
- **#141** — Serialize models + metadata (blocked by #138, #139, #140)

## Queue status

- Completed: #136, #137, #138, #139
- Next: #140
- Remaining: 4 issues in P1.5 queue
