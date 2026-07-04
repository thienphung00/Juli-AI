# Handoff: ship complete — Issue #137

## Shipped

- Issue #137 closed
- PR #145 merged — commit `703c08e`

## What shipped

- `src/modules/ml/features` — three builders (`build_seller_stage_features`, `build_anomaly_features`, `build_ad_features`) returning `FeatureMatrix`
- Group A anomaly columns match `feature-store-schema.md`; ADR-011 forbidden-column guard
- Manifest `dataset_dir` field for parquet resolution
- ADR-014 documenting the feature builder module
- 4 AC-mapped unit tests in `tests/unit/test_feature_builder.py`

## Rollback

```bash
git revert 703c08e
```

No migrations or runtime config.

## Follow-up work

- **#138** — Seller stage classifier (blocked by: none — #137 complete)
- **#139** — Anomaly detector trainer (parallel with #138, #140)
- **#140** — Ad performance analyzer trainer (parallel with #138, #139)

## Queue status

- Completed: #136, #137
- Next: #138, #139, #140 (parallel after #137)
- Remaining: 6 issues in P1.5 queue
