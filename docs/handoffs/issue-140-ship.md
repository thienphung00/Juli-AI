# Handoff: ship complete — Issue #140

## Shipped

- Issue #140 closed
- PR #148 merged — commit `226ad8b`

## What shipped

- `src/modules/ml/ad_performance` — `train_ad_performance`, `predict_ad_action`, `build_ad_training_frame`
- ROAS regressor + scale/cut/hold action classifier on campaign/day features with account baselines
- ROAS MAPE on held-out date window in `metrics.json`
- Sparse ad history → low-confidence `hold` without raising
- CLI `train-ad` writes metrics + training log JSON
- ADR-017 documenting the ad performance trainer module
- 7 AC-mapped tests in `tests/unit/test_ad_performance_trainer.py`

## Rollback

```bash
git revert 226ad8b
```

No migrations or runtime config.

## Follow-up work

- **#141** — Serialize models + metadata + smoke tests (blocked by: #138, #139, #140 — all complete)
- **#142** — Feature specs, inference signatures, threshold sign-off (HITL)

## Queue status

- Completed: #136, #137, #138, #139, #140
- Next: #141
- Remaining: 3 issues in P1.5 queue
