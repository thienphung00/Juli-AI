# Handoff: focus → implementation — Issue #{N}

## Issue
- **#{N}** — {title}
- **EXECUTION slice:** {slice}
- **Parent:** #{prd} · **Blocked by:** {deps}
- **Executor domain:** {ui-ux | backend | data-platform | machine-learning | integrations}

## Branch
- `{feature|fix}/issue-{N}-{slug}`

## phaseRunId
- {issueId}-{date}-{short-hash} — use across all runtime artifacts for this run

## Implementation artifact (end of Executor phase)
- `artifacts/implementations/implementation-issue-{N}.json`

## Acceptance criteria
- {AC bullets from GitHub issue}

## Context loaded
| Area | Files |
|------|-------|
| Architecture | {files} |
| Module | {MODULE.md paths} |

## Standards applied
- {reliability, security, etc.}

## Plugin skills & MCP
- {skills from skill-catalog}

## Implementation approach
**Dependency order:** {order}

### New files
| File | Purpose |
|------|---------|

### Modified files
| File | Change |
|------|--------|

### Key patterns
- {decisions with rationale}

### Tests (built-in TDD)
1. RED: {behavior}
2. GREEN: {implementation target}

## DO NOT touch
- {out-of-scope modules}
