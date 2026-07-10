# Task Type D: Multi-Agent Workflow

**taskType:** `multi-agent-workflow`  
**Framework:** [`agent-runtime-benchmarks.md`](../../architecture/agent-runtime-benchmarks.md)

## Purpose

Measure handoff quality, context routing, and phase execution across the full agent
runtime. Scores context efficiency and stability across Planning → Implementation →
Review + Testing → Harness Optimization.

## Fixture profile

| Field | Value |
|-------|-------|
| Executor domain | Any — fixture specifies expected domain |
| Scope | Small change requiring explicit Context Plan and two handoff templates |
| Planning | **Required** — `focus → to-prd` or issue with full AC |
| Example | Implement issue #N using templates: focus-implementation → implementation-review → review-validate → validation-meta |

## Acceptance criteria template

```markdown
## Acceptance Criteria
1. Context Plan produced before implementation (checkpoint in handoff)
2. All runtime artifacts committed with consistent phaseRunId
3. Validation passes on first run OR retryCount documented with root cause
4. Harness optimization proposes at least one measurable improvement
```

## Expected artifacts

| Artifact | Required fields |
|----------|-----------------|
| Implementation | `contextFilesLoaded`, `skillsLoaded`, `phaseRunId` |
| Review | `sourceImplementationArtifact`, `phaseRunId` |
| Validation | `sourceReviewArtifact`, `phaseRunId` |
| Harness optimization | `contextTransferCount`, `phasePath` includes all phases, `proposedOptimization` |

## Deterministic checks

| Check ID | Pass condition |
|----------|----------------|
| `phase_run_id_consistent` | Same `phaseRunId` on impl, review, validation when all present |
| `context_documented` | `implementation.contextFilesLoaded.length >= 3` (EXECUTION, map, MODULE) |
| `skills_documented` | `implementation.skillsLoaded` includes domain executor skill |
| `handoff_chain_complete` | All four artifact types exist on branch |
| `context_transfer_count` | `harnessOptimization.contextTransferCount` recorded (>= 0) |
| `optimization_proposed` | `harnessOptimization.proposedOptimization.summary` non-empty |
| `validation_pass_or_retry` | `validation.status == PASS` OR (`retryCount > 0` AND `rootCauseCategory` set) |
| `review_loops_acceptable` | `retryCount <= 2` |

## Baseline metrics emphasis

| Group | Primary metrics |
|-------|-----------------|
| Efficiency | `contextFilesLoaded.length`, `contextTransferCount`, `tokenUsageTotal` |
| Stability | `retryCount`, `reviewFailureRate`, `validationFailureRate` |
| Cost | `toolInvocationCount`, `tokenUsageTotal` |

## Handoff templates (required)

Use these templates in order:

1. [`focus-implementation.md`](../../templates/handoffs/focus-implementation.md)
2. [`implementation-review.md`](../../templates/handoffs/implementation-review.md)
3. [`review-validate.md`](../../templates/handoffs/review-validate.md)
4. [`validation-meta.md`](../../templates/handoffs/validation-meta.md)

## Planning score inputs

- Context Plan checkbox section completed in handoff
- Executor domain in Context Plan matches `implementation.executorDomain`

## Anti-patterns (fail benchmark)

- Missing `phaseRunId` correlation across artifacts
- Harness optimization skipped after validation
- Implementation without prior Context Plan (for first-run benchmark)
