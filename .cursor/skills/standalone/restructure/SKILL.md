---
name: refactor
description: >-
  Safely restructures the codebase while preserving all existing behaviour — the
  invariant is that the same tests pass before and after every issue. Use when the
  user says "restructure", "v1A to v1B", "leaner codebase", or when
  invoked by the refactor pipeline in core-orchestration.mdc.
---

# Refactor

Safely restructure the codebase from one form to another while preserving
all existing behaviour. The invariant is: the same tests pass before and after every issue.

## Entry

1. Invoke `grill-with-docs` to answer: what must be preserved? what is allowed to change?
   Produce explicit answers to both before writing any code.
2. Read `CONTEXT.md` and `docs/decisions/` before invoking `improve-codebase-arch`.
   Pass any relevant ADRs to `improve-codebase-arch` as constraints — it must not re-suggest
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
