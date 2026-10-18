# LEGACY — the PRD → issue → slice agent loop

**Status (fast track P53, DECISIONS D62, owner-approved 2026-10-18):** marker only. Nothing
here was moved, deleted or changed in behaviour.

The Meta Agent optimisation loop this directory drives (PRD → GitHub issue → slice →
Executor/Review agents → validate gates → release evidence JSON, ADR-003) is no longer how
work ships. Since DECISIONS **D4** the fast track (`fasttrack/`: SPEC, DECISIONS, LOG, DEBT,
`fasttrack/check.sh`, `.github/workflows/fasttrack-deploy.yml`) replaced it on
`fasttrack/optimize-product`. New work should not add issues, slices, `artifacts/` evidence or
`status/` records here.

## Keep everything: what still reads this directory

| Reader | What it uses |
|---|---|
| `fasttrack/check.sh` (the fast-track deploy gate) | `scripts/ci/ensure_postgrest_client_roles.py`, `scripts/ci/check_public_schema_privileges.py` (migration step) |
| `.github/workflows/pr.yml` (PRs to `main`) | ~13 `scripts/ci/*.py` gates, among them `check_import_boundaries.py`, `check_ownership_registry.py`, `check_public_schema_privileges.py`, `generate_validation_artifact.py`, `wave_manifest.py`, and the blocking `scripts/validate/check_*` set (`check_module_boundaries`, `check_module_drift`, `check_adr`, `check_done_md`) |
| `.github/workflows/release.yml` | `scripts/ci/generate_release_artifact.py` → `artifacts/releases/` |
| `.github/workflows/architecture-audit.yml` (daily) | `scripts/ci/audit_module_drift.py`, `audit_cycles.py`, `audit_module_size.py`, `audit_pipeline_coverage.py` |
| `.github/workflows/release-shape.yml` | path trigger on `scripts/**` |
| ~84 test files under `tests/` | the CI scripts above, `scripts/validate/*`, `config/`, `artifacts/` (e.g. `test_import_boundaries`, `test_status_record_gate`, `test_three_tier_ci_contract`, `tests/harness/test_module_md_sync_parser.py`) |
| `.claude/hooks/_gate_rules.py`, `.claude/settings.json` | `config/agent-runtime.config.yml`, `artifacts/workflow-cache`, `scripts/meta_prepare_executor.py` |
| `CLAUDE.md` authority chain | `docs/agent-runtime.md` |
| backend CI thresholds | `scripts/ci/ml_thresholds.py` (gates `backend/.../ai/`), `scripts/ci/medallion_one_writer.py` |

Retiring any of it means changing those readers first (Phase 2 of the 2026-10-18 audit, owner
decision per item).
