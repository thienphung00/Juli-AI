# Task Type B: Bug Fix

**taskType:** `bug-fix`  
**Framework:** [`agent-runtime-benchmarks.md`](../../architecture/agent-runtime-benchmarks.md)

## Purpose

Measure root cause accuracy, regression test quality, and validation through artifacts.
The harness must show Red → Green TDD with a failing test that reproduces the bug.

## Fixture profile

| Field | Value |
|-------|-------|
| Executor domain | Match affected surface (`backend`, `ui-ux`, etc.) |
| Scope | One bug, one module, minimal fix |
| Planning | Optional — issue should describe observed vs expected |
| Example | Fix incorrect status code on error path; add regression test |

## Acceptance criteria template

```markdown
## Acceptance Criteria
1. Regression test reproduces the bug (fails before fix)
2. Fix makes regression test pass without breaking existing tests
3. Root cause documented in implementation summary
```

## Expected artifacts

| Artifact | Required fields |
|----------|-----------------|
| Implementation | `redGreenRefactorEvidence` with failing then passing command output |
| Review | `status` PASS, no CRITICAL findings |
| Validation | `status` PASS, all gate checks PASS |
| Harness optimization | `rootCauseCategory` set when retries or review loops occurred |

## Deterministic checks

| Check ID | Pass condition |
|----------|----------------|
| `tdd_red_reproduces_bug` | First cycle in `redGreenRefactorEvidence` has `failingTestEvidence` |
| `tdd_green_passes` | Same or later cycle has `passingTestEvidence` |
| `regression_test_added` | `testsAdded` includes regression test node id |
| `root_cause_documented` | `implementationSummary` non-empty |
| `validation_pass` | `validation.status == PASS` |
| `sibling_tests_pass` | `validation.testsFailed == 0` when `testsExecuted > 0` |
| `harness_root_cause` | If `retryCount > 0`, `harnessOptimization.rootCauseCategory != none` |

## Baseline metrics emphasis

| Group | Primary metrics |
|-------|-----------------|
| Quality | `testPassRate`, review `severity` |
| Efficiency | `toolInvocationCount` (fewer loops = better) |
| Stability | `retryCount`, `reviewFailureRate` |

## Bug-fix specific signals

- `implementation.assumptions` should state reproduction environment
- `implementation.risks` should note blast radius of fix
- Review `criticalFindings` must be empty for PASS benchmark

## Anti-patterns (fail benchmark)

- Fix without failing test first (no RED evidence)
- Broad refactor bundled with bug fix (task type C instead)
- `reviewFailures > 0` with `status == PASS`
