---
name: restructure
description: >-
  Execute mechanical codebase moves when target structure is already decided — same tests
  must pass before and after every issue. Use when the user says "restructure", "v1A to v1B",
  or when invoked by the refactor pipeline in core-orchestration.mdc. For architecture
  discovery or "leaner codebase" exploration, use improve-codebase-architecture instead.
---

# Restructure

Execute mechanical codebase moves from one structure to another while preserving all
existing behaviour. The invariant is: the same tests pass before and after every issue.

## Entry

1. **Architecture not yet decided?** Use `improve-codebase-architecture` first — it discovers
   structural friction and proposes target shape. This skill executes mechanical moves only
   after current structure, target structure, and gating tests are explicit.
2. Invoke `grill-with-docs` to answer: what must be preserved? what is allowed to change?
   Produce explicit answers to both before writing any code.
3. Read `CONTEXT.md` and `docs/adr/` — pass relevant ADRs as constraints; do not re-open
   decisions already recorded there.

## Issue creation

- Each refactor issue must state: current structure, target structure, and the test(s) that gate it.
- Issues that would require new tests are escalated to Implementation (Executor Agent). Flag them; do not silently convert.

## Per-issue loop constraints

- Run the full test suite before making any change. Record the result.
- Make only the structural change described in the issue. No opportunistic improvements.
- Run the full test suite after the change. Compare to the before result.
- If any previously-passing test now fails: stop, surface the failure, do not patch the test.
  The test is the source of truth, not the refactor plan.

## Surfaces and test commands

| Surface | Command |
|---------|---------|
| iOS (`ios/`) | `xcodebuild test -scheme [scheme] -destination 'platform=iOS Simulator,...'` |
| Web (`web/`) | `pnpm test` or `npx jest` |
| Backend (`src/`) | `pytest` |

## Handoff

Always write a handoff at the end. Include what structural changes were completed
and which issues remain open.
