---
name: fix-bug
description: >-
  Systematic bug-fix pipeline that chains skills in sequence:
  qa → [focus → tdd → review → ship] per issue.
  Each skill receives a handoff from the previous and produces a handoff for
  the next. Use when fixing a reported bug, investigating a failing test,
  triaging a Sentry/production error, or patching a regression.
---

# Fix Bug

Orchestrates the full bug-fix lifecycle by invoking skills in a fixed sequence. Every fix starts with reproduction, not code changes.

## Pipeline

```
┌──────┐
│  qa  │ gather & file issues
└──┬───┘
   │
   ▼
┌──────────────────────────┐
│  Per-issue loop:         │
│                          │
│  ┌───────┐               │
│  │ focus │ context       │
│  └───┬───┘               │
│      ▼                   │
│  ┌───────┐               │
│  │  tdd  │ reproduce+fix │
│  └───┬───┘               │
│      ▼                   │
│  ┌────────┐              │
│  │ review │ PR           │
│  └───┬────┘              │
│      ▼                   │
│  ┌───────┐               │
│  │ ship  │ merge         │
│  └───────┘               │
│                          │
│  (repeat next issue)     │
└──────────────────────────┘
```

---

## Input types

**Type A — Incorrect Acceptance Criteria**
User pastes or describes a failing acceptance criterion:
the behaviour the code exhibits vs the behaviour the criterion specifies.
Entry point: qa creates the GitHub issue directly.
  gh issue create --title "AC mismatch: [criterion summary]" --label bug \
    --body "[failing criterion]\n\nActual behaviour: [description]"

**Type B — Terminal error**
User pastes a raw stack trace, crash log, or error output.
Entry point: invoke diagnose before qa.
diagnose completes root-cause analysis → qa creates the issue with the root cause in the body.
  gh issue create --title "[error type]: [one-line summary]" --label bug \
    --body "[root cause from diagnose]\n\nReproduction: [steps from diagnose]"

**Routing rule**
If the input contains a stack trace, exception type, line number reference,
or build error output → Type B.
If the input is a description of mismatched behaviour against a spec → Type A.
When ambiguous, ask the user one question: "Is this a crash/error output or a behaviour mismatch?"

---

## Phase 1: QA

**Skill:** `qa`

**What it does:**
- Runs an interactive QA session where the user describes bugs conversationally
- Asks at most 2–3 clarifying questions per report (expected vs actual, steps to reproduce, consistent vs intermittent)
- Explores the codebase for domain language and behavior context (NOT to find a fix)
- Assesses scope: single issue or breakdown into multiple issues
- Files GitHub issues immediately via `gh issue create` with user-facing language (no file paths or line numbers)

**Handoff → implementation loop:**

```markdown
## Handoff: qa → implementation

### Issue Queue (dependency order)
1. #[N1] — [title] — blocked by: none
2. #[N2] — [title] — blocked by: #N1
...

### Severity Assessment
- SEV level per issue (per `ship` severity definitions)
- Response time expectations

### Implementation Order
Process issues top-to-bottom. For each issue: run focus → tdd → review → ship.
If a report required architectural change to fix, note it — may need `grill-with-docs` first to update canonical docs (`EXECUTION.md`, `system-design.md`, architecture, ADRs).
```

---

## Phase 2: Implementation Loop (per issue)

For each issue in the queue, run these four skills in sequence:

### 2a. Focus

**Skill:** `focus`

**What it does:**
- Reads the issue's reproduction steps and expected/actual behavior
- Classifies what the bug involves (API, data, AI, frontend, infra)
- Loads context scoped narrowly to the affected module:
  - The module's `MODULE.md` (from `docs/architecture/map.md`)
  - Immediate dependencies (upstream callers, downstream services)
  - Applicable standards (reliability if error-handling bug, security if vulnerability, etc.)
- Identifies relevant MCP tools and plugin skills from [`.cursor/skills/skill-catalog/SKILL.md`](../../skill-catalog/SKILL.md) (`catalog` frontmatter)
- Keeps context narrow — only what's needed to understand the affected code path

**Handoff → tdd:**

```markdown
## Handoff: focus → tdd

### Issue
- #[number] — [title]
- Expected behavior: [from issue]
- Actual behavior: [from issue]
- Reproduction steps: [from issue]

### Context Loaded
- Architecture: [files loaded]
- Module docs: [MODULE.md files loaded]
- Standards applied: [reliability, security, observability — which ones]
- Rules active: [which .cursor/rules/*.mdc apply]

### Plugin skills & MCP (from skill-catalog)
- Plugin skills to load: [/skill-name, …]
- MCP servers: [serverName from catalog, …]
- Catalog: `.cursor/skills/skill-catalog/SKILL.md`

### Affected Code Path
- Entry point: [API endpoint, handler, or function]
- Files to investigate: [list with purpose]
- Immediate dependencies: [upstream/downstream]

### DO NOT Touch
- [Files/modules explicitly out of scope — fix the bug, nothing else]
```

### 2b. TDD

**Skill:** `tdd`

**What it does:**
- Uses the focus handoff to understand the affected code path
- **RED**: Writes a failing test that reproduces the bug — test name describes the bug, not the fix
  - The test must fail for the same reason the bug occurs
  - If it passes, the test doesn't reproduce the bug — refine until RED
- **GREEN**: Applies the smallest change that makes the failing test pass without breaking existing tests
  - Fix the bug, nothing else — no refactoring, no "while I'm here" improvements
  - One logical change — each file touch directly required by the fix
- **REFACTOR (implementation)**: Only after GREEN, minimal cleanup directly related to the fix:
  - Extract shared validation if same guard needed elsewhere
  - Add type annotations that would have caught the bug
  - Improve error messages that made diagnosis harder
- **REFACTOR (tests & fixtures)**: Still only after GREEN, clean up the regression test and fixtures:
  - Extract repeated setup into fixtures/factories
  - Tighten assertions to the smallest stable contract
  - Keep tests deterministic (no shared state, no ordering dependency)
- Checks for siblings — same bug pattern elsewhere — files follow-up issues if found
- Commits working code with passing tests on a fix branch

**Test placement guidelines:**

Prefer matching the existing `tests/unit/test_*.py` patterns in this repo:

| Bug Type | Test Location | Pattern |
|----------|--------------|---------|
| API endpoint returns wrong status/body | `tests/unit/test_api*.py` | `httpx.AsyncClient` + `ASGITransport` + assert status/shape |
| Auth/authZ behavior | `tests/unit/test_get_current_user.py` (or similar) | dependency override `get_current_user` + assert 401/403/200 |
| Service/domain logic incorrect | `tests/unit/test_*.py` | direct async call + assert outcome |
| Data/repo behavior incorrect | `tests/unit/test_repos.py` (or similar) | use async `session` fixture + assert DB state |

**Handoff → review:**

```markdown
## Handoff: tdd → review

### Issue
- #[number] — [title]

### Branch
- `fix/issue-[N]-[description]`

### Root Cause
- Category: [missing guard | wrong assumption | state mutation | race condition | type mismatch | off-by-one | stale cache]
- Explanation: [why this happened — root cause, not symptom]

### Changes Summary
- New files: [list]
- Modified files: [list]
- Database migrations: [migration file names, if any]

### Tests Written
- [test_file.py::test_name] — reproduces the exact bug conditions
- [test_file.py::test_name] — [additional edge case, if any]

### Test Results
- Regression test passes (was RED, now GREEN)
- All [N] pre-existing tests still pass

### Fix Verification
- [x] New regression test passes
- [x] All pre-existing tests still pass
- [x] Fix addresses root cause, not just symptom
- [x] No unrelated changes included

### Sibling Check
- Searched for same pattern — [found N instances / none found]
- Follow-up issues filed: #[XX], #[YY] (if applicable)

### Notes for Reviewer
- [Anything unusual, trade-offs made, areas to pay attention to]
```

### 2c. Review

**Skill:** `review`

**What it does:**
- Reads the tdd handoff to understand the root cause and fix
- Runs the full test suite to verify nothing is broken
- Scans changes across validation domains scoped to the fix:
  - **Reliability** — does the fix handle all variants of the triggering condition?
  - **Security** — if the bug was exploitable, is the fix complete?
  - **Observability** — are there logs/metrics that would catch this class of bug earlier?
  - **Siblings** — validates the sibling check was thorough
- Produces a findings report (critical / warning / info)
- Fixes critical findings in-place
- Opens a PR via `gh pr create` with the bug-fix PR template

**PR body template:**

```markdown
## What
Fix [describe the bug] reported in #[issue].

## Root Cause
[Technical explanation of why this happened]

## Fix
[What changed and why this is the correct fix]

## Regression Test
- `tests/path/test_file.py::test_name` — reproduces the exact conditions

## Sibling Check
- [ ] Searched for same pattern — [found N instances / none found]
- [ ] Filed follow-up issues for siblings: #XX, #YY (if applicable)

## Rollback
[How to revert if something goes wrong]
```

**Handoff → ship:**

```markdown
## Handoff: review → ship

### Issue
- #[number] — [title]

### PR
- PR: #[pr-number] — [title]
- URL: [PR URL]
- Branch: `fix/issue-[N]-[description]` → `main`

### Review Status
- Critical findings: [N] — all resolved
- Warnings: [N] — [resolved/accepted with rationale]
- Info: [N] — noted

### Test Results
- All tests passing (including regression test + pre-existing)
- Lint: clean
- Type-check: clean

### Checklist
- [x] Regression test reproduces bug and now passes
- [x] No secrets committed
- [x] Error handling on affected I/O paths
- [x] Structured logging on error paths
- [x] Sibling check completed
- [x] Migrations reversible (if applicable)
```

### 2d. Ship

**Skill:** `ship`

**What it does:**
- Reads the review handoff
- Validates the PR passes all pre-merge gate checks (lint, type-check, tests, security scan)
- Evaluates deployment readiness (migration safety, rollback plan)
- Merges the PR if all gates pass
- Closes the corresponding GitHub issue
- Records what was shipped for the next issue in the queue

**Handoff → next issue (or completion):**

```markdown
## Handoff: ship → next issue

### Shipped
- Issue #[number] closed
- PR #[pr-number] merged to main
- Commit: [short SHA]

### Deployment Notes
- Migration applied: [yes/no]
- Rollback: [how to revert]

### Queue Status
- Completed: #N1, #N2
- Next: #N3 — [title]
- Remaining: [count] issues
```

---

## Completion

When all issues in the queue are shipped:

```markdown
## Bugs Fixed: [Session Summary]

### Issues Shipped
- #N1 — [title] — PR #[pr] — root cause: [category]
- #N2 — [title] — PR #[pr] — root cause: [category]

### What Was Fixed
- [One paragraph summary of the bugs resolved]

### Regression Tests Added
- [N] new regression tests across [M] test files
- All reproduction steps verified

### Sibling Issues Filed
- #[XX] — [pattern found elsewhere]
- (or: none — all instances covered)

### Follow-ups
- [ ] [Anything deferred or noted during fix process]
```

---

## When NOT to Use This Workflow

| Situation | Use Instead |
|-----------|-------------|
| Building a new feature | `workflow/build-feature` |
| Performance degradation (no functional bug) | `review` + profiling |
| Flaky test (not a production bug) | `tdd` to stabilize the test |
| Security vulnerability (needs immediate action) | Hotfix process in `ship` (SEV1) |
| Bug requires architectural change to fix properly | `grill-with-docs` first to update canonical docs, then come back here |
| Single skill in isolation (just need to file issues) | Invoke `qa` directly |
