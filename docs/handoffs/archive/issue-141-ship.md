# Handoff: ship complete — Issue #141

## Shipped

- Issue #141 closed
- PR #149 merged — commit `72c89f6`

## What shipped

- `src/modules/ml/artifacts` — `publish_model`, `load_model`, `run_smoke_test`, `evaluate_promotion_status`
- Versioned layout: `models/{suite}/{version}/model.joblib + metadata.json + metrics.json`
- Promotion gate: `promoted` | `experimental` based on provisional backtest thresholds
- Feature schema hash from authoritative column tuples
- Golden-fixture smoke tests for all three suites
- ADR-018 documenting the artifact publisher module
- 10 AC-mapped tests in `tests/unit/test_model_artifacts.py`

## Rollback

```bash
git revert 72c89f6
```

No migrations or runtime config.

## Follow-up work

- **#142** — Feature specs, inference signatures, threshold sign-off (HITL)
- **#143** — Publish Phase 2 target architecture (blocked by #141, #142)

## Queue status

- Completed: #136, #137, #138, #139, #140, #141
- Next: #142 (HITL — requires Product threshold sign-off)
- Remaining: 2 issues in P1.5 queue
