# Handoff: validation → Meta (harness optimization) — Issue #{N}

## Issue
- **#{N}** — {title}
- **phaseRunId:** {phaseRunId}

## Source artifacts consumed

| Artifact | Path | Key signals |
|----------|------|-------------|
| Implementation | `artifacts/implementations/implementation-issue-{N}.json` | `executorDomain`, `toolInvocationCount`, `redGreenRefactorEvidence` |
| Review | `artifacts/reviews/review-issue-{N}.json` | `reviewFailures`, `severity`, domain findings |
| Validation | `artifacts/validation/validation-issue-{N}.json` | `validationFailures`, `testsPassed`, `readyForMerge` |

## Harness optimization artifact (required every run)

- Path: `artifacts/optimization/harness-issue-{N}-{phaseRunId}.json`
- `appliedStatus`: proposed
- `rootCauseCategory`: {category}
- `proposedOptimization`: {one-line summary}

### baselineMetrics snapshot

| Metric | Value |
|--------|-------|
| executionTimeMs | {ms} |
| tokenUsageTotal | {n} |
| testPassRate | {0-1} |
| coveragePercentage | {%} |
| reviewFailureRate | {0-1} |
| validationFailureRate | {0-1} |
| retryCount | {n} |
| toolInvocationCount | {n} |

## Product-development optimization (optional)

Emit only when repeated pattern detected across issues:

- Path: `artifacts/optimization/product-development-{id}.json`
- `acceptedByArchitect`: pending
- `recommendedBacklogItem.title`: {title}

## Next step

- If `autoApplyEligible`: Architect reviews proposed harness change before apply (Phase 6)
- If validation failed: route back to Executor or Review — do not ship

Schema: [`docs/architecture/agent-runtime-artifacts.md`](../../architecture/agent-runtime-artifacts.md)
