---
name: diagnose
description: >-
  Disciplined diagnosis loop for terminal errors, crashes, and hard bugs where the
  root cause is not immediately obvious. Use when the user says "diagnose", "hard bug",
  "non-deterministic failure", "performance regression", or before Executor
  implementation on a hard bug (after `qa` files the issue).
---

# Diagnose

Disciplined diagnosis loop for terminal errors, crashes, and hard bugs
where the root cause is not immediately obvious.

Human-in-the-loop — confirm with user before each phase transition.

## Phase 1 — Reproduce

Reproduce the error in a local or test environment.
If you cannot reproduce, ask the user for the exact steps.
Do not proceed to Phase 2 until reproduction is confirmed.

## Phase 2 — Minimise

Reduce the reproduction case to the smallest possible trigger.
Remove variables one at a time. Document what you removed and whether the error persisted.

## Phase 3 — Hypothesise

State 2–3 candidate root causes, ranked by likelihood.
For each: what evidence supports it, what evidence would rule it out.
Present to the user and confirm which to investigate first.

## Phase 4 — Instrument

Add targeted logging, assertions, or breakpoints to confirm or rule out the top hypothesis.

| Surface | Instrumentation |
|---------|----------------|
| Swift/iOS | `os_log` at `.debug` level — remove before ship |
| Next.js | `console.debug` statements — remove before ship |
| Python/FastAPI | `logging.debug()` — never log seller financial fields |

## Phase 5 — Fix

Write the fix only after Phase 4 confirms the root cause.
The fix must address the root cause, not mask the symptom.

## Phase 6 — Regression test

Write a test that would have caught this bug before the fix.
This test becomes part of the issue's acceptance criterion.

## Output to qa

```markdown
Root cause: [one sentence]
Reproduction steps: [numbered list]
Fix applied: [one sentence]
Regression test: [test file and test name]
```
