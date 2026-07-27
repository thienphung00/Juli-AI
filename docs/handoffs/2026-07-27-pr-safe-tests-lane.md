# Handoff — PR-safe Tests lane (ADR-040 #1–#7)

## Session summary

Architect grill settled ADR-040. Executed architecture candidates **#1–#7**: PR-safe Tests wiring, demo/live ownership, migration_heavy / phase_scaffold lean-outs, CI meta-test retirement, validate wiring moved to harness, Phase 2.5 scaffold deferred to merge_group.

## Decisions made

- PR-safe: exclude `live`, `demo_contract`, `migration_heavy`, `phase_scaffold` (+ cov≥80, 30s/15m)
- merge_group `test`: includes migration_heavy + phase_scaffold; excludes live/demo_contract
- PR migration paths: extra `migration_heavy` step
- `live` → `test-live-sandbox` (merge_group only)
- `demo_contract` → `demo-deploy-contracts`
- Deleted `test_validation_checks_wiring.py`; CHECKS + generator-fail live in harness

## Current state

- Slice committed (or pending commit) on focused paths only
- Collect (approx): PR-safe ~984 · demo 87 · live 3 · migration_heavy 8 · phase_scaffold 97

## Next steps

1. Land PR and confirm green PR + merge_group jobs
2. Optional: further harness/unit overlap trims (#6 optional MERGE list)

## Open questions

- None for this slice.
