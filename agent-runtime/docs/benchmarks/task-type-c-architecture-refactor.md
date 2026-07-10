# Task Type C: Architecture Refactoring

**taskType:** `architecture-refactor`  
**Framework:** [`agent-runtime-benchmarks.md`](../../architecture/agent-runtime-benchmarks.md)

## Purpose

Measure architecture preservation, dependency management, and review effectiveness during
refactors. No net-new product behavior — structure changes only.

## Fixture profile

| Field | Value |
|-------|-------|
| Executor domain | Usually `backend` or `data-platform` |
| Scope | Extract/move symbols within Tier 1/2 modules; no new external APIs |
| Planning | Required — document modules affected and ADR need |
| Example | Extract helper from service into `src/shared/utils/` with tests unchanged |

## Acceptance criteria template

```markdown
## Acceptance Criteria
1. All existing tests pass without behavior change
2. Module boundaries respected per map.md
3. MODULE.md public interfaces updated if exports change
4. ADR filed if breaking interface change (should be false for pure refactor)
```

## Expected artifacts

| Artifact | Required fields |
|----------|-----------------|
| Implementation | `filesModified` lists only in-scope modules; `risks` notes boundary impact |
| Review | `architectureFindings`, `moduleDrift` false, `modulesTouched` accurate |
| Validation | `checks[module_boundaries]` PASS, `checks[module_md_sync]` PASS |
| Harness optimization | `contextFilesLoaded` includes `map.md` and affected `MODULE.md` |

## Deterministic checks

| Check ID | Pass condition |
|----------|----------------|
| `boundaries_pass` | `validation.checks` entry `module_boundaries` status PASS |
| `drift_pass` | `validation.checks` entry `module_md_sync` status PASS |
| `no_cycles` | `module_boundaries` details `cycles` empty |
| `adr_check_pass` | `validation.checks` entry `adr_requirement` status PASS |
| `tests_preserved` | `validation.testsFailed == 0` |
| `arch_findings_reviewed` | If `architectureFindings` non-empty, all severity != CRITICAL or status FAIL |
| `impl_no_new_ac` | `testsAdded` empty OR only refactor-safe test moves documented |

## Baseline metrics emphasis

| Group | Primary metrics |
|-------|-----------------|
| Quality | `reviewFailureRate`, architecture finding count |
| Efficiency | `contextFilesLoaded.length` (should include map + MODULE.md) |
| Stability | `validationFailureRate` |

## Planning score inputs

- Fixture declares allowed modules; `modulesTouched` subset of allowed set
- `interfaceChanges` in review artifact documented when public symbols move

## Anti-patterns (fail benchmark)

- New feature behavior smuggled into refactor task
- Cross-module imports outside `MODULE.md` public surfaces
- Skipping `module_md_sync` gate
