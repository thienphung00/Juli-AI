# Handoff: implementation → review — Issue #{N}

## Issue
- **#{N}** — {title}

## Branch
- `{feature|fix}/issue-{N}-{slug}`

## Executor domain
- {ui-ux | backend | data-platform | machine-learning | integrations}

## Implementation artifact (required)
- Path: `artifacts/implementations/implementation-issue-{N}.json`
- `phaseRunId`: {phaseRunId}
- Generator: `python scripts/ci/generate_implementation_artifact.py --issue {N} --executor-domain {domain}`

## Changes summary
- New: {files}
- Modified: {files}
- Migrations: {if any}
- MODULE.md added: {if any}

## Tests written
| Test | Behavior verified |
|------|-------------------|
| {file}::{name} | {AC mapping} |

## TDD evidence
- RED: {failing test / command output summary}
- GREEN: {passing test summary}
- Refactor: {if any}

## Test results
- All {N} tests passing
- No pre-existing tests broken

## Acceptance criteria status
- [x] {AC} — {test}
- [ ] {AC} — deferred: {reason}

## Notes for reviewer
- {trade-offs, risks}

## Next step
Review Agent: load implementation artifact → run `intent-review` → run `guardrails` → write `artifacts/intent-reviews/intent-review-issue-{N}.json` then `artifacts/reviews/review-issue-{N}.json`
