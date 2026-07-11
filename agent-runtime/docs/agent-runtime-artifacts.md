# Agent Runtime Artifacts

**Status:** Published (Agent Runtime Phase 5)  
**Authority:** [ADR-003](../adr/003-ai-native-cicd-policy.md) for CI gate fields; this file for runtime artifact routing, schemas, and persistence  
**Canonical runtime:** [`agent-runtime.md`](agent-runtime.md)

Machine-readable execution feedback for the agent-phase harness. Source documents
(PRDs, ADRs, GitHub issues, handoff markdown) are planning inputs — they are **not**
substitutes for runtime artifacts.

---

## Artifact taxonomy

| Artifact | Producer | Primary consumers | Path pattern |
|----------|----------|-------------------|--------------|
| **implementation** | Executor Agent | Review Agent, Meta Agent | `agent-runtime/artifacts/implementations/implementation-issue-<n>.json` |
| **review** | Review Agent (`review` skill) | Validate, `pr.yml`, Meta Agent | `agent-runtime/artifacts/reviews/review-issue-<n>.json` |
| **validation** | Review Agent (`validate` skill, `pr.yml`) | Ship, Meta Agent | `agent-runtime/artifacts/validation/validation-issue-<n>.json` |
| **harness_optimization** | Meta Agent | Harness config, benchmark reruns | `agent-runtime/artifacts/optimization/harness-issue-<n>-<phaseRunId>.json` |
| **product_development_optimization** | Meta Agent (occasional) | Architect Agent backlog | `agent-runtime/artifacts/optimization/product-development-<id>.json` |
| **parent_cache** | Planning / `grill-with-docs` + `prompt-caching` | All children of parent #P | `agent-runtime/artifacts/grill-cache/parent-cache-issue-<P>.json` |
| **grill_cache** | `grill-with-docs`, `prompt-caching`, agents per phase | Meta, Executor, Review, Validate (child #N only) | `agent-runtime/artifacts/grill-cache/grill-cache-issue-<n>.json` |
| **release** *(ADR-003)* | Ship skill, `release.yml` | Rollback / hotfix agents | `agent-runtime/artifacts/releases/release-<version>.json` |
| **audit** *(ADR-003)* | `architecture-audit.yml` | Triage to GitHub issues | `agent-runtime/artifacts/validation/audit-<type>-<date>.json` |

JSON Schema definitions: [`schemas/`](schemas/).

---

## Routing diagram

```mermaid
flowchart LR
  Executor["Executor Agent"] --> Impl["implementation-artifact"]
  Impl --> Review["Review Agent"]
  Review --> RevArt["review-artifact"]
  RevArt --> Validate["validate"]
  Validate --> ValArt["validation-artifact"]
  ValArt --> Ship["ship-ready"]
  Impl --> Meta["Meta Agent"]
  RevArt --> Meta
  ValArt --> Meta
  Meta --> Harness["harness-optimization-artifact"]
  Meta --> Product["product-development-optimization-artifact"]
  Product --> Architect["Architect Agent backlog"]
  Harness --> Config["Harness config / focus routing"]
```

No execution artifact bypasses Meta after validation completes. Meta may read source
documents for explanation, but scoring and optimization must use artifact fields
where deterministic evidence exists.

---

## ADR-003 compatibility

ADR-003 review and validation artifacts remain the **CI gate contract**. Agent Runtime
schemas **extend** those contracts — they do not replace gate-required fields.

| Concern | ADR-003 / CI gate field | Meta optimization field | Notes |
|---------|-------------------------|-------------------------|-------|
| Review pass/fail | `status` | `reviewStatus` (optional mirror) | CI reads `status` only |
| Critical findings | `criticalFindings[]` | `findings`, `reviewFailures` | Gate uses `criticalFindings`; Meta aggregates `reviewFailures` count |
| Acceptance mapping | `testCoverage.acceptance` | — | Unchanged for `check_acceptance_mapping.py` |
| Validation pass/fail | `status`, `readyForMerge` | `readyForShip` (optional mirror) | CI reads `status` and `readyForMerge` |
| Per-check results | `checks[]` | `validationFailures` | Gate uses `checks`; Meta uses failure count |

**Phase 4** updates skills to emit optimization fields. Gate scripts under
`agent-runtime/scripts/validate/` continue to validate only ADR-003 required fields.

---

## Persistence policy

### Commit on feature branches

| Path | Commit? | Rationale |
|------|---------|-----------|
| `agent-runtime/artifacts/reviews/review-issue-*.json` | **Yes** | ADR-003: CI `pr.yml` requires branch-persistent review artifacts |
| `agent-runtime/artifacts/validation/validation-issue-*.json` | **Yes** | ADR-003: ship and CI consume validation artifacts |
| `agent-runtime/artifacts/implementations/implementation-issue-*.json` | **Yes** | Small JSON; Meta optimization input |
| `agent-runtime/artifacts/optimization/harness-issue-*.json` | **Yes** | Primary Meta output; benchmark before/after comparison |
| `agent-runtime/artifacts/optimization/product-development-*.json` | **Yes** | Architect backlog routing evidence |
| `agent-runtime/artifacts/grill-cache/parent-cache-issue-*.json` | **Yes** | Parent/PRD constant across child issues |
| `agent-runtime/artifacts/grill-cache/grill-cache-issue-*.json` | **Yes** | Per-child workflow cache (unique load profile) |
| `agent-runtime/artifacts/releases/release-*.json` | **Yes** | ADR-003 rollback metadata |
| `agent-runtime/artifacts/validation/audit-*.json` | **Yes** | Nightly audit summaries (structured JSON) |

### Never commit

| Path | Rationale |
|------|-----------|
| `artifacts/runtime/raw/` | Large raw tool logs, full test stdout, screenshots |
| `artifacts/runtime/logs/` | Verbose session telemetry |
| `.agent-state/` | Local session resumption only |

### Editing rules

- **Review artifact:** regenerate via `review` skill or `generate_review_artifact.py` — do not edit from `validate`.
- **Validation artifact:** produced by `validate` skill or `generate_validation_artifact.py` after gates pass.
- **Implementation / optimization artifacts:** produced by Executor / Meta agents per Phase 4 skill updates; manual edits only for harness benchmark fixtures.

See [`artifacts/README.md`](../../agent-runtime/artifacts/README.md) for directory layout.

---

## Schema versions

All runtime artifacts include `schemaVersion` (semver string). Current version: **`1.0.0`**.

| Schema file | `artifactType` enum value |
|-------------|---------------------------|
| `implementation-artifact.schema.json` | `implementation` |
| `review-artifact.schema.json` | `review` |
| `validation-artifact.schema.json` | `validation` |
| `harness-optimization-artifact.schema.json` | `harness_optimization` |
| `product-development-optimization-artifact.schema.json` | `product_development_optimization` |
| `parent-cache-artifact.schema.json` | `parent_cache` |
| `grill-cache-artifact.schema.json` | `grill_cache` |

Bump `schemaVersion` minor for backward-compatible field additions; major for breaking
changes to required CI gate fields (requires ADR and gate script updates).

---

## Field reference (by artifact)

### implementation-artifact

Executor → Review + Meta execution signal.

**Required:** `schemaVersion`, `artifactType`, `issueId`, `executorDomain`, `phaseRunId`,
`startedAt`, `completedAt`, `executionDurationMs`, `toolsUsed`, `toolInvocationCount`,
`contextFilesLoaded`, `skillsLoaded`, `filesModified`, `testsAdded`, `testsUpdated`,
`redGreenRefactorEvidence`, `implementationSummary`, `assumptions`, `risks`.

**Optional:** `tokenUsage` (input/output/total when available).

`redGreenRefactorEvidence` is an array of TDD cycles: failing test evidence, passing test
evidence, refactor notes, and commands/results when available.

`executorDomain` enum: `ui-ux` | `backend` | `data-platform` | `machine-learning`.

### review-artifact

Review → Validate + Meta quality signal. **All ADR-003 fields remain required for CI.**

**ADR-003 required (CI):** `id`, `issue`, `status`, `criticalFindings`, `modulesTouched`,
`testCoverage` (with `acceptance.total`, `acceptance.mapped`, `acceptance.mappings`).

**Meta extensions (optional until Phase 4):** `schemaVersion`, `artifactType`,
`sourceImplementationArtifact`, `reviewStatus`, `reviewFailures`, `findings`, `severity`,
`securityFindings`, `architectureFindings`, `maintainabilityFindings`,
`suggestedRemediation`, `staticAnalysisExecuted`, `dynamicTestsExecuted`, `reviewDurationMs`.

### validation-artifact

Validate → Ship + Meta objective-quality signal.

**ADR-003 required (CI):** `id`, `issue`, `status`, `checks`, `readyForMerge`.

**Meta extensions (optional until Phase 4):** `schemaVersion`, `artifactType`,
`sourceReviewArtifact`, `testsExecuted`, `testsPassed`, `testsFailed`, `coveragePercentage`,
`benchmarkStatus`, `executionDurationMs`, `retryCount`, `validationFailures`, `readyForShip`.

`readyForShip` mirrors `readyForMerge` when both are present; CI continues to read
`readyForMerge`.

### harness-optimization-artifact

Meta → Harness config. Emitted after every complete agent-phase run (Phase 6 automation).

Captures the **eight baseline metrics:**

| Metric | Primary artifact field(s) |
|--------|---------------------------|
| Execution Time | `executionDurationMs`, `baselineMetrics.executionTimeMs` |
| Token Usage | `tokenUsage`, `baselineMetrics.tokenUsageTotal` |
| Test Pass Rate | `baselineMetrics.testPassRate` (from validation artifact) |
| Test Coverage | `baselineMetrics.coveragePercentage` |
| Review Failure Rate | `reviewFailures`, `baselineMetrics.reviewFailureRate` |
| Validation Failure Rate | `validationFailures`, `baselineMetrics.validationFailureRate` |
| Retry Count | `retryCount`, `baselineMetrics.retryCount` |
| Tool Invocation Count | `toolInvocationCount`, `baselineMetrics.toolInvocationCount` |

**Required:** `schemaVersion`, `artifactType`, `issueId`, `phaseRunId`, `phasePath`,
`executorAssigned`, `contextFilesLoaded`, `skillsLoaded`, `tokenUsage`, `executionDurationMs`,
`reviewFailures`, `validationFailures`, `retryCount`, `contextTransferCount`,
`toolInvocationCount`, `baselineMetrics`, `rootCauseCategory`, `proposedOptimization`,
`expectedMetricImpact`, `harnessConfigTargets`, `autoApplyEligible`, `appliedStatus`,
`sourceArtifacts`.

`appliedStatus` enum: `proposed` | `accepted` | `rejected` | `applied` | `measured`.

`rootCauseCategory` enum: `context_underloaded`, `context_overloaded`, `wrong_executor_domain`,
`insufficient_tdd_evidence`, `review_gap`, `validation_failure`, `tool_overuse`, `phase_loop`,
`artifact_incomplete`, `architecture_unclear`.

### product-development-optimization-artifact

Meta → Architect backlog (occasional). Emitted when repeated evidence indicates process or
architecture improvement.

**Required:** `schemaVersion`, `artifactType`, `id`, `sourceIssueIds`, `detectedPattern`,
`rootCauseCategory`, `planningSignal`, `architectureSignal`, `decompositionSignal`,
`reviewSignal`, `recommendedBacklogItem`, `requiresADR`, `requiresPRDUpdate`,
`requiresIssueTemplateUpdate`, `priority`, `evidenceArtifacts`, `acceptedByArchitect`.

**Optional:** `sourceBenchmarkRunIds`.

`acceptedByArchitect` enum: `pending` | `accepted` | `rejected`.

`priority` enum: `low` | `medium` | `high`.

---

## phaseRunId convention

Correlates artifacts from one complete agent-phase execution:

```
<issueId>-<ISO8601-date>-<short-hash>
```

Example: `42-2026-06-23-a1b2c3`

All artifacts from the same run share `phaseRunId`. Harness optimization artifacts
append it to the filename for uniqueness when multiple runs exist per issue.

---

## Validation workflow

1. **CI gates (mandatory):** `agent-runtime/scripts/validate/*.py` — ADR-003 fields only.
2. **Schema check (advisory):** validate JSON against `schemas/*.schema.json`
   before committing optimization artifacts or during benchmark runs.
3. **Meta scoring:** derive the eight baseline metrics from `baselineMetrics`
   on harness optimization artifacts; compare across benchmark reruns per
   [`agent-runtime-benchmarks.md`](agent-runtime-benchmarks.md).

---

## Related documents

| Document | Owns |
|----------|------|
| [`agent-runtime.md`](agent-runtime.md) | Agent phases, ownership, optimization loop intent |
| [`agent-runtime-benchmarks.md`](agent-runtime-benchmarks.md) | Benchmark protocol and scoring |
| [ADR-003](../adr/003-ai-native-cicd-policy.md) | CI enforcement, gate ordering |
| [`docs/deployment/implementation-guide.md`](../ci/implementation-guide.md) | Gate scripts, ADR-003 schema examples |
| [`artifacts/README.md`](../../agent-runtime/artifacts/README.md) | Directory layout and commit policy |
