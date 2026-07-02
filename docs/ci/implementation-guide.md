# AI-Native CI/CD: Implementation Guide

Companion to [ADR-003](../decisions/003-ai-native-cicd-policy.md). Defines the
artifact schemas and points at the concrete files that implement each gate.

This is a Python/FastAPI + Next.js codebase ([ADR-001](../decisions/001-keep-python-fastapi.md)).
All gate scripts are Python. The Next.js dashboard in [`web/`](../../web/) keeps
its own `npm` tooling but is invoked from the same workflows.

## Layout

```
.github/
  workflows/
    pr.yml                       # PR validation
    release.yml                  # Production deployment
    architecture-audit.yml       # Nightly drift / cycle / size audit

scripts/
  ci/                            # Generators (called by skills + CI)
    generate_review_artifact.py
    generate_validation_artifact.py
    generate_release_artifact.py
    audit_module_drift.py
    audit_cycles.py
    audit_module_size.py
  validate/                      # PR gates (exit 0/1)
    check_review_artifact.py
    check_acceptance_mapping.py
    check_module_boundaries.py
    check_module_drift.py
    check_handoff.py
    check_adr.py
    check_done_md.py

artifacts/
  reviews/                       # review-issue-<n>.json (commit on branch)
  validation/                    # validation-issue-<n>.json + audit-<date>.json
  implementations/               # implementation-issue-<n>.json (Agent Runtime)
  optimization/                  # harness + product-development optimization JSON
  benchmarks/                    # benchmark-run-<id>.json reports
  releases/                      # release-<version>.json
  runtime/raw/                   # gitignored verbose logs
  runtime/logs/                  # gitignored session telemetry

docs/
  schemas/agent-runtime/         # JSON Schema for runtime artifacts
  decisions/                     # NNN-slug.md ADRs
  system-design.md               # technical design (phase-mapped)
  architecture/map.md            # authoritative module list

EXECUTION.md                     # root single source of truth (plan + ownership)
done.md                          # root definition-of-done checklist
```

## Skill / Agent Phase Wiring

Harness routing: [`docs/architecture/agent-runtime.md`](../architecture/agent-runtime.md).

```
Planning:      focus -> to-prd -> to-issues
Implementation: focus (Meta) -> Executor (built-in TDD)
Review:        review -> validate -> ship
Bug filing:    qa -> focus -> Executor -> review -> validate -> ship
```

| Producer | Output | Consumer |
|----------|--------|----------|
| Executor Agent | `artifacts/implementations/implementation-issue-<n>.json` | `review` skill, Meta Agent |
| `review` skill | `artifacts/reviews/review-issue-<n>.json` | `validate` skill, `pr.yml`, Meta Agent |
| `validate` skill (and `pr.yml`) | `artifacts/validation/validation-issue-<n>.json` | `ship` skill, Meta Agent |
| Meta Agent (Focus, post-validation) | `artifacts/optimization/harness-issue-<n>-<phaseRunId>.json` | Harness config, benchmarks |
| Meta Agent (occasional) | `artifacts/optimization/product-development-<id>.json` | Architect backlog |
| `ship` skill (and `release.yml`) | `artifacts/releases/release-<version>.json` | Future agents (rollback) |
| `architecture-audit.yml` (nightly) | `artifacts/validation/audit-<date>.json` | Triage to GitHub issues |

## Artifact Schemas

**Agent Runtime (Phase 3):** JSON Schema definitions and persistence policy live in
[`docs/architecture/agent-runtime-artifacts.md`](../architecture/agent-runtime-artifacts.md)
and [`docs/schemas/agent-runtime/`](../schemas/agent-runtime/). The review and validation
schemas below remain the **ADR-003 CI gate contract**. Agent Runtime extends them with
optional Meta optimization fields (`reviewFailures`, `baselineMetrics`, etc.) — gate scripts
validate only the fields documented here.

| Artifact | ADR-003 CI fields | Meta-only extensions | Schema |
|----------|-------------------|----------------------|--------|
| Review | `status`, `criticalFindings`, `testCoverage` | `findings`, `reviewDurationMs`, … | `review-artifact.schema.json` |
| Validation | `status`, `checks`, `readyForMerge` | `coveragePercentage`, `retryCount`, … | `validation-artifact.schema.json` |
| Implementation | — | Full schema (Phase 4 emission) | `implementation-artifact.schema.json` |
| Harness optimization | — | Eight baseline metrics in `baselineMetrics` | `harness-optimization-artifact.schema.json` |

### Review Artifact

`artifacts/reviews/review-issue-<n>.json`

```json
{
  "id": "review-issue-123",
  "issue": 123,
  "timestamp": "2026-05-27T10:30:00Z",
  "reviewedBy": "review skill",
  "status": "PASS | PASS_WITH_WARNINGS | FAIL",
  "summary": "High-level summary",
  "criticalFindings": [
    {
      "type": "boundary_violation | test_gap | drift | interface_change | other",
      "module": "src/auth",
      "description": "What was found and why it matters",
      "severity": "CRITICAL | WARNING",
      "actionRequired": true,
      "suggestion": "How to fix"
    }
  ],
  "modulesTouched": ["src/auth", "src/api"],
  "interfaceChanges": [
    {
      "module": "src/auth",
      "interface": "verify_supabase_jwt",
      "changeType": "added | modified | removed",
      "breaking": false,
      "description": "What changed and impact"
    }
  ],
  "moduleDrift": false,
  "driftDetails": [],
  "testCoverage": {
    "acceptance": {
      "total": 5,
      "mapped": 5,
      "unmapped": [],
      "mappings": [
        {"criterion": "User can log in via demo entry", "test": "web/src/__tests__/test_ui_only_login.test.tsx"}
      ]
    },
    "unit": {"passed": 42, "failed": 0}
  },
  "recommendations": [],
  "approvalReady": true
}
```

**Status semantics:** `status: "FAIL"` is required when any
`criticalFindings[*].severity == "CRITICAL"`, `actionRequired: true`, or a
mandatory fail trigger fires (CRITICAL security, production data exposure, test
regression, incomplete acceptance criteria, unresolved prior blockers, missing
ML gates). `status: "PASS_WITH_WARNINGS"` is required when WARNING findings
exist (and no CRITICAL/actionRequired/mandatory fail). Legacy top-level
`warnings[]` is rejected by CI — findings must live in `criticalFindings`.
`PASS_WITH_WARNINGS` blocks merge until each WARNING has `acceptanceByReviewer`,
`ownerAck`, and `fixedInCommit` or `shipAsIsReason`, plus `reviewerSignoff` and
`ownerSignoff`. Regenerate with
`python scripts/ci/generate_review_artifact.py --issue <n>` (preserves existing
fields; use `--fresh` to reset) or batch-fix with
`python scripts/ci/normalize_review_artifacts.py`. CI rejects status/findings mismatches.

**Hotfix override:** set `overriddenMerge` with `timestamp`, `overriddenBy`, `reason`,
`incidentLink` to merge despite overridable mandatory fails (see
[ADR-003](../decisions/003-ai-native-cicd-policy.md)). CRITICAL security and
production data exposure are never overridable.

**Post-deploy tracking:** append to `productionOutcome.incidents[]` with
`linkedFinding` (matches `criticalFindings[].id`) when a shipped-as-is risk
materializes in production.

**ML gates:** `mlGates` booleans plus source scan in `scripts/ci/ml_thresholds.py`.
Optional `mlGates.thresholds` cross-checks declared values against `thresholds.py`.

### Validation Artifact

`artifacts/validation/validation-issue-<n>.json`

```json
{
  "id": "validation-issue-123",
  "issue": 123,
  "timestamp": "2026-05-27T10:32:00Z",
  "validatedBy": "validate skill",
  "status": "PASS | FAIL",
  "passedChecks": 12,
  "failedChecks": 0,
  "checks": [
    {
      "name": "review_artifact_present",
      "status": "PASS | FAIL",
      "description": "Review artifact present and structurally valid",
      "details": {}
    },
    {
      "name": "acceptance_criteria_mapped",
      "status": "PASS | FAIL",
      "details": {"total": 5, "mapped": 5, "unmapped": []}
    },
    {
      "name": "module_boundaries",
      "status": "PASS | FAIL",
      "details": {"violations": [], "cycles": [], "modulesTouched": 2}
    },
    {
      "name": "module_md_sync",
      "status": "PASS | FAIL",
      "details": {"drift": [], "missingInterfaces": []}
    },
    {
      "name": "handoff_structure",
      "status": "PASS | FAIL",
      "details": {"required": false, "missingFields": []}
    },
    {
      "name": "adr_requirement",
      "status": "PASS | FAIL",
      "details": {"architecturalChange": false, "adrPresent": true}
    },
    {
      "name": "done_md_completion",
      "status": "PASS | FAIL",
      "details": {"unchecked": []}
    }
  ],
  "overallSummary": "All validation checks passed.",
  "readyForMerge": true
}
```

### Release Artifact

`artifacts/releases/release-<version>.json`

```json
{
  "version": "1.2.3",
  "timestamp": "2026-05-27T14:30:00Z",
  "commit": "abc123def456",
  "branch": "main",
  "deployedBy": "release.yml",
  "environment": "production",
  "featuresShipped": [
    {"id": 123, "title": "Demo login", "modules": ["web"], "breaking": false}
  ],
  "bugsFixed": [{"id": 130, "title": "Order webhook duplicate detection"}],
  "adrsAdded": [{"number": "003", "title": "AI-Native CI/CD Policy", "file": "docs/decisions/003-ai-native-cicd-policy.md"}],
  "migrations": [
    {"name": "20260527_add_users_table", "type": "schema", "reversible": true,
     "rollbackPlan": "alembic downgrade -1"}
  ],
  "rollbackPlan": {
    "procedure": "Revert to previous tag, then `alembic downgrade -1`",
    "estimatedDowntime": "< 5 minutes",
    "dataLossPotential": false,
    "criticalSteps": [
      "Stop FastAPI workers",
      "alembic downgrade -1",
      "Redeploy previous Railway image",
      "Restart workers"
    ],
    "testRollback": true
  },
  "deploymentMetadata": {
    "durationMinutes": 5,
    "stagingValidated": true,
    "smokeTestsPassed": true,
    "healthChecksPassed": true
  },
  "notes": ""
}
```

## Workflow Reference

The actual GitHub Actions YAML lives in
[`.github/workflows/`](../../.github/workflows/). Skim that directory directly;
this guide does not duplicate the YAML. What each workflow does:

| Workflow | Trigger | Jobs |
|----------|---------|------|
| [`pr.yml`](../../.github/workflows/pr.yml) | `pull_request` | lint-and-typecheck (ruff + mypy), test (pytest with Postgres + Redis), migration-check (alembic up/down/up), frontend (npm in `web/`), validate-artifacts (`scripts/validate/*.py`), generate-validation-artifact, status-check |
| [`release.yml`](../../.github/workflows/release.yml) | `push` to `main` | build, deploy-staging (Railway), smoke, deploy-production (Railway), generate-release-artifact, github-release |
| [`architecture-audit.yml`](../../.github/workflows/architecture-audit.yml) | `cron: '0 2 * * *'`, `workflow_dispatch` | audit-drift, audit-cycles, audit-size, summarize, file-issue-on-critical |

## Script Reference

The actual Python sources live in [`scripts/`](../../scripts/). Each script is
a single file, stdlib-only, with `--help`. Summary:

| Script | Reads | Writes / Exit code |
|--------|-------|-------------------|
| [`scripts/ci/generate_implementation_artifact.py`](../../scripts/ci/generate_implementation_artifact.py) | `--issue`, `--executor-domain`, optional `--input-json` | Writes `artifacts/implementations/implementation-issue-<n>.json` |
| [`scripts/ci/generate_review_artifact.py`](../../scripts/ci/generate_review_artifact.py) | `--issue`, optional `--input-json` | Writes `artifacts/reviews/review-issue-<n>.json` (ADR-003 + Meta fields) |
| [`scripts/ci/generate_validation_artifact.py`](../../scripts/ci/generate_validation_artifact.py) | Runs all checks | Writes `artifacts/validation/validation-issue-<n>.json` (ADR-003 + Meta fields), exit 0 if PASS |
| [`scripts/ci/generate_release_artifact.py`](../../scripts/ci/generate_release_artifact.py) | `--version`, `--commit`, git history | Writes `artifacts/releases/release-<version>.json` |
| [`scripts/ci/audit_module_drift.py`](../../scripts/ci/audit_module_drift.py) | `MODULE.md` files vs Python AST | Writes `artifacts/validation/audit-drift-<date>.json` |
| [`scripts/ci/audit_cycles.py`](../../scripts/ci/audit_cycles.py) | `docs/architecture/map.md`, AST imports | Writes `artifacts/validation/audit-cycles-<date>.json` |
| [`scripts/ci/audit_module_size.py`](../../scripts/ci/audit_module_size.py) | LOC per module | Writes `artifacts/validation/audit-size-<date>.json` |
| [`scripts/validate/check_review_artifact.py`](../../scripts/validate/check_review_artifact.py) | `--issue` | Exit 0 if PASS, 1 otherwise |
| [`scripts/validate/check_implementation_artifact.py`](../../scripts/validate/check_implementation_artifact.py) | `--issue` | Exit 0 if PASS, 1 otherwise |
| [`scripts/validate/check_acceptance_mapping.py`](../../scripts/validate/check_acceptance_mapping.py) | review artifact | Exit 0/1 |
| [`scripts/validate/check_module_boundaries.py`](../../scripts/validate/check_module_boundaries.py) | git diff + AST + map.md | Exit 0/1 |
| [`scripts/validate/check_module_drift.py`](../../scripts/validate/check_module_drift.py) | `MODULE.md` vs AST | Exit 0/1 |
| [`scripts/validate/check_handoff.py`](../../scripts/validate/check_handoff.py) | `docs/handoffs/*.md` | Exit 0/1 |
| [`scripts/validate/check_adr.py`](../../scripts/validate/check_adr.py) | review artifact + `docs/decisions/` | Exit 0/1 |
| [`scripts/validate/check_done_md.py`](../../scripts/validate/check_done_md.py) | root `done.md` | Exit 0/1 |
| [`scripts/validate/check_critical_findings_resolved.py`](../../scripts/validate/check_critical_findings_resolved.py) | review artifact mandatory fail triggers | Exit 0/1 |
| [`scripts/validate/check_findings_acknowledged.py`](../../scripts/validate/check_findings_acknowledged.py) | WARNING finding signoffs | Exit 0/1 |
| [`scripts/validate/check_reviewer_signoff.py`](../../scripts/validate/check_reviewer_signoff.py) | `reviewerSignoff` | Exit 0/1 |
| [`scripts/validate/check_owner_signoff.py`](../../scripts/validate/check_owner_signoff.py) | `ownerSignoff` | Exit 0/1 |
| [`scripts/validate/check_ml_gates.py`](../../scripts/validate/check_ml_gates.py) | `mlGates` for ML modules | Exit 0/1 |

## Acceptance Criteria Mapping

Issue bodies use a `## Acceptance Criteria` section with one numbered item per
criterion. Every criterion must map to a named test in `tests/`. Mapping is
recorded in the review artifact's
`testCoverage.acceptance.mappings[]`. `check_acceptance_mapping.py` verifies:

1. Number of items equals `testCoverage.acceptance.total`.
2. Every mapping points to a `pytest` node id (`path::test_name`) that exists.
3. The criterion text is reflected in the test name (substring match,
   case-insensitive, ignoring underscores).

Example mapping:

```json
{"criterion": "User can log in via demo entry",
 "test": "web/src/__tests__/test_ui_only_login.test.tsx"}
```

## Handoff Validation

The `docs/handoffs/` registry was removed in the seller-money rescope;
cross-session ownership and continuity now live in
[`EXECUTION.md`](../../EXECUTION.md) (per-slice status). See
[ADR-003](../decisions/003-ai-native-cicd-policy.md) for the policy.

`check_handoff.py` remains as a dormant gate: if any `docs/handoffs/*.md` file is
present it validates *shape only* (a `Status` per issue, `Modules` rows from
[`docs/architecture/map.md`](../architecture/map.md), and a bootstrap prompt
block); it never auto-generates a handoff and passes when no handoff exists.

## Module Boundary Rules

Authoritative module list: [`docs/architecture/map.md`](../architecture/map.md).

Forbidden:
- Cross-module imports outside of public symbols listed in the importee's `MODULE.md`.
- Cyclic dependencies between modules.

Warning (not failure):
- More than 3 modules touched in a single PR. Defer to the disjoint-modules rule
  in [`.cursor/rules/issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc).

`check_module_boundaries.py` parses imports with `ast`, builds a directed graph,
and runs Tarjan's SCC. Tier 3 utility modules without `MODULE.md` are excluded.

## ADR Convention

| Field | Convention |
|-------|------------|
| Filename | `NNN-slug.md` (3-digit, hyphenated slug) — NOT `adr-NNN.md` |
| Required sections | Status / Date / Context / Decision / Rationale / Consequences |
| Registry | [`docs/decisions/README.md`](../decisions/README.md) |

`check_adr.py` enforces the filename pattern and the required sections.
