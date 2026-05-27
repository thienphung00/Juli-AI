---
name: build-feature
description: >-
  End-to-end feature pipeline that chains skills in sequence:
  discover → to-prd → to-issues → [focus → tdd → review → ship] per issue.
  Each skill receives a handoff from the previous and produces a handoff for
  the next. Use when building a new feature from idea to deployed code.
---

# Build Feature

Orchestrates the full feature lifecycle by invoking skills in a fixed sequence. Each skill owns one phase and passes a structured handoff to the next.

## Pipeline

```
┌───────────┐    ┌──────────┐    ┌───────────┐
│  discover │───▶│  to-prd  │───▶│ to-issues │
└───────────┘    └──────────┘    └─────┬─────┘
                                       │
                            ┌──────────▼──────────┐
                            │  Per-issue loop:     │
                            │                      │
                            │  ┌───────┐           │
                            │  │ focus │ context   │
                            │  └───┬───┘           │
                            │      ▼               │
                            │  ┌───────┐           │
                            │  │  tdd  │ implement │
                            │  └───┬───┘           │
                            │      ▼               │
                            │  ┌────────┐          │
                            │  │ review │ PR       │
                            │  └───┬────┘          │
                            │      ▼               │
                            │  ┌───────┐           │
                            │  │ ship  │ merge     │
                            │  └───────┘           │
                            │                      │
                            │  (repeat next issue) │
                            └──────────────────────┘
```

---

## Phase 1: Discover

**Skill:** `discover`

**What it does:**
- Explores the codebase and relevant docs (`docs/architecture/map.md`, MODULE.md files, existing API contracts)
- Asks the user clarifying questions (business goals, constraints, dependencies, failure modes)
- Identifies affected architectural layers and cross-cutting concerns
- Produces understanding of scope, dependencies, and edge cases

**Handoff → to-prd:**

```markdown
## Handoff: discover → to-prd

### Feature Summary
[One paragraph: what this feature does and why]

### Scope
- Affected layers: [list from architecture-context.md]
- Services to modify: [existing modules]
- New services needed: [if any]
- Database changes: [yes/no + brief]
- API surface changes: [breaking/additive/none]

### Constraints
- [Budget, timeline, compliance, model tier — anything gathered]

### Edge Cases & Failure Modes
- [Enumerated list from discovery questions]

### Open Questions
- [Anything still unresolved — to-prd will note these as assumptions]
```

---

## Phase 2: To-PRD

**Skill:** `to-prd`

**What it does:**
- Synthesizes the discover handoff and codebase understanding into a structured PRD
- Proposes deep modules (small interface, deep logic) rather than file-level plans
- Does a lightweight alignment check with the user
- Submits the PRD as a GitHub issue via `gh issue create`

**Handoff → to-issues:**

```markdown
## Handoff: to-prd → to-issues

### PRD Issue
- GitHub issue: #[number] — [title]
- URL: [issue URL]

### Modules Identified
- [Module 1]: [responsibility] — [public interface summary]
- [Module 2]: [responsibility] — [public interface summary]

### User Stories Count
- [N] user stories covering [scope areas]

### Testing Decisions
- Modules to test: [list]
- Test style: [integration-first, golden datasets, etc.]

### Implementation Decisions
- [Key architectural choices made in the PRD]
```

---

## Phase 3: To-Issues

**Skill:** `to-issues`

**What it does:**
- Reads the PRD issue
- Breaks it into thin vertical slices (tracer bullets) — each independently demoable
- Marks each as AFK (autonomous) or HITL (needs human)
- Quizzes the user on granularity and dependencies
- Creates GitHub issues in dependency order via `gh issue create`

**Handoff → implementation loop:**

```markdown
## Handoff: to-issues → implementation

### Issue Queue (dependency order)
1. #[N1] — [title] — AFK — blocked by: none
2. #[N2] — [title] — AFK — blocked by: #N1
3. #[N3] — [title] — HITL — blocked by: #N1
...

### Parent PRD
- GitHub issue: #[prd-number]

### Implementation Order
Process issues top-to-bottom. Skip HITL issues until the user resolves them.
For each AFK issue: run focus → tdd → review → ship.
```

---

## Phase 4: Implementation Loop (per issue)

For each issue in the queue, run these four skills in sequence:

### 4a. Focus

**Skill:** `focus`

**What it does:**
- Reads the issue's acceptance criteria and the parent PRD
- Classifies what the implementation involves (API, data, AI, frontend, infra)
- Loads the right context: MODULE.md files, architecture docs, API contracts
- Loads applicable rules (`.cursor/rules/`) and standards based on detection
- Identifies relevant MCP tools and plugins needed (Supabase MCP for DB work, Context7 for library docs, shadcn for UI components, etc.)
- Produces a context loading plan with explicit include/exclude

**Handoff → tdd:**

```markdown
## Handoff: focus → tdd

### Issue
- #[number] — [title]
- Acceptance criteria: [copied from issue]

### Context Loaded
- Architecture: [files loaded]
- Module docs: [MODULE.md files loaded]
- Standards applied: [reliability, security, observability, performance — which ones]
- Rules active: [which .cursor/rules/*.mdc apply]

### MCP Tools Available
- [supabase]: for DB migrations, RLS policies, schema inspection
- [context7]: for library/framework API docs
- [shadcn]: for UI components (if frontend work)
- [figma]: for design reference (if UI work)

### Implementation Approach
- New files: [list with purpose]
- Modified files: [list with what changes]
- Dependency order: data → service → API → frontend
- Key patterns to follow: [from loaded context]

### DO NOT Touch
- [Files/modules explicitly out of scope]
```

### 4b. TDD

**Skill:** `tdd`

**What it does:**
- Uses the focus handoff to understand what to build and which tools to use
- Plans behaviors to test (from acceptance criteria)
- Implements via red-green-refactor, one behavior at a time:
  - **RED**: write a failing integration test using public interfaces
  - **GREEN**: minimal production code to pass
  - **REFACTOR**: clean up while green
- Uses MCP tools as needed (Supabase MCP for migrations, Context7 for API references, shadcn for component installation)
- Creates new MODULE.md files when adding new modules (per `docs/architecture/map.md`)
- Commits working code with passing tests on a feature branch

**Handoff → review:**

```markdown
## Handoff: tdd → review

### Issue
- #[number] — [title]

### Branch
- `feature/issue-[N]-[description]`

### Changes Summary
- New files: [list]
- Modified files: [list]
- Database migrations: [migration file names, if any]
- New modules added: [with MODULE.md — if any]

### Tests Written
- [test_file.py::test_name] — [what behavior it verifies]
- [test_file.py::test_name] — [what behavior it verifies]

### Test Results
- All [N] tests passing
- No pre-existing tests broken

### Acceptance Criteria Status
- [x] Criterion 1 — covered by test_name
- [x] Criterion 2 — covered by test_name
- [ ] Criterion 3 — deferred (explain why, if any)

### Notes for Reviewer
- [Anything unusual, trade-offs made, areas to pay attention to]
```

### 4c. Review

**Skill:** `review`

**What it does:**
- Reads the tdd handoff to understand what changed
- Runs the full test suite to verify nothing is broken
- Scans changes across all validation domains (reliability, maintainability, security, observability, performance)
- Produces a findings report (critical / warning / info)
- Fixes critical findings in-place
- Opens a PR via `gh pr create` with the ship PR template (What / Why / How / Testing / Rollback)

**Handoff → ship:**

```markdown
## Handoff: review → ship

### Issue
- #[number] — [title]

### PR
- PR: #[pr-number] — [title]
- URL: [PR URL]
- Branch: `feature/issue-[N]-[description]` → `main`

### Review Status
- Critical findings: [N] — all resolved
- Warnings: [N] — [resolved/accepted with rationale]
- Info: [N] — noted

### Test Results
- All tests passing (including new + pre-existing)
- Lint: clean
- Type-check: clean

### Checklist
- [x] Tests added for all acceptance criteria
- [x] No secrets committed
- [x] Error handling on all I/O paths
- [x] Structured logging on error paths
- [x] Migrations reversible (if applicable)
```

### 4d. Ship

**Skill:** `ship`

**What it does:**
- Reads the review handoff
- Validates the PR passes all pre-merge gate checks (lint, type-check, tests, security scan)
- Evaluates deployment readiness (migration safety, rollback plan, feature flag)
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
- Feature flag: [name, if applicable]
- Rollback: [how to revert]

### Queue Status
- Completed: #N1, #N2
- Next: #N3 — [title]
- Remaining: [count] issues
- Blocked: #[N] waiting on [HITL resolution / other issue]
```

---

## Completion

When all issues in the queue are shipped:

```markdown
## Feature Complete: [Feature Name]

### PRD
- Issue #[prd-number] — [title]

### Issues Shipped
- #N1 — [title] — PR #[pr]
- #N2 — [title] — PR #[pr]
- #N3 — [title] — PR #[pr]

### What Was Built
- [One paragraph summary of the delivered feature]

### Architecture Changes
- New modules: [list with MODULE.md links]
- Modified modules: [list]
- New migrations: [list]

### Test Coverage
- [N] new tests across [M] test files
- All acceptance criteria verified

### Follow-ups
- [ ] [Anything deferred or noted during implementation]
```

---

## When NOT to Use This Workflow

| Situation | Use Instead |
|-----------|-------------|
| Fixing a bug | `workflow/fix-bug` |
| Single skill in isolation (just need a PRD, just need issues) | Invoke that skill directly |
| AI-specific implementation details | `build-ai` alongside `tdd` in the implementation loop |
| Hotfix / SEV1 incident | `ship` incident response directly |
