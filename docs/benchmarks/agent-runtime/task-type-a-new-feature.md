# Task Type A: New Feature Implementation

**taskType:** `new-feature`  
**Framework:** [`agent-runtime-benchmarks.md`](../../architecture/agent-runtime-benchmarks.md)

## Purpose

Measure end-to-end feature delivery through artifacts. Planning quality is scored from
source docs and issue decomposition; execution quality from implementation, review, and
validation artifacts.

## Fixture profile

| Field | Value |
|-------|-------|
| Executor domain | `backend` (default) or per slice |
| Scope | One acceptance criterion, one module, &lt; 200 LOC |
| Planning | Required on first run |
| Example | Add a single read-only API endpoint with one integration test |

## Acceptance criteria template

```markdown
## Acceptance Criteria
1. GET /api/v1/<resource> returns 200 with expected JSON envelope
2. Unauthenticated request returns 401
```

## Expected artifacts

| Artifact | Required fields |
|----------|-----------------|
| Implementation | `testsAdded`, `redGreenRefactorEvidence`, `filesModified`, `executorDomain` |
| Review | `testCoverage.acceptance.mappings` complete, `status` PASS |
| Validation | `status` PASS, `readyForMerge` true |
| Harness optimization | Full `baselineMetrics`, `proposedOptimization` |

## Deterministic checks

| Check ID | Pass condition |
|----------|----------------|
| `ac_tests_added` | `implementation.testsAdded.length >= acceptance.total` |
| `ac_mapped` | `review.testCoverage.acceptance.mapped == acceptance.total` |
| `tdd_cycles` | `implementation.redGreenRefactorEvidence.length >= 1` |
| `validation_pass` | `validation.status == PASS` |
| `impl_duration_recorded` | `implementation.executionDurationMs > 0` |
| `retry_acceptable` | `validation.retryCount <= 1` |

## Baseline metrics emphasis

| Group | Primary metrics |
|-------|-----------------|
| Quality | `testPassRate`, `coveragePercentage` |
| Speed | `executionTimeMs` |
| Stability | `validationFailureRate`, `retryCount` |

## Planning score inputs

- Issue or fixture includes numbered acceptance criteria
- `modulesTouched` matches fixture module list
- ADR check passes when interface changes declared

## Anti-patterns (fail benchmark)

- Implementation artifact missing TDD evidence for behavior changes
- Review PASS with unmapped acceptance criteria
- Validation artifact synthesized without running gate scripts
