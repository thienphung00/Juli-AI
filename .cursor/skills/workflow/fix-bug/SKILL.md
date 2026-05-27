---
name: fix-bug
description: >-
  Systematic bug-fix workflow: reproduce with a failing test, diagnose root cause,
  fix minimally, and verify the regression net holds. Uses TDD's red-green loop
  to ensure bugs stay fixed. Use when fixing a reported bug, investigating a
  failing test, triaging a Sentry/production error, or patching a regression.
---

# Fix Bug

Turns a bug report into a verified fix with a regression test. Every bug fix starts with reproduction, not code changes.

## Workflow

```
Report → Reproduce (RED) → Diagnose → Fix (GREEN) → Verify → PR
   ↑          ↑                ↑           ↑           ↑       ↑
 issue       tdd            focus        minimal     review   ship
```

## Step 1: Understand the Bug

Gather from the report (GitHub issue, Sentry alert, user message, or failing CI):

- [ ] **What** — expected vs. actual behavior
- [ ] **Where** — which endpoint, page, or function
- [ ] **When** — always, intermittent, or under specific conditions
- [ ] **Impact** — severity level (SEV1-4 per `ship` definitions)
- [ ] **Reproduce steps** — exact inputs or sequence to trigger

If the report is vague, ask clarifying questions before proceeding. Do not guess at the bug.

## Step 2: Load Context via Focus

Invoke `focus` scoped to the affected module:

- The module's `MODULE.md` (from `docs/architecture/map.md`)
- Immediate dependencies (upstream callers, downstream services)
- Relevant standards (reliability if it's an error-handling bug, security if it's a vulnerability)

Keep context narrow — only load what's needed to understand the affected code path.

## Step 3: Reproduce with a Failing Test (RED)

**Write a test that fails for the same reason the bug occurs.** This is non-negotiable — it proves you understand the bug and prevents regressions.

```python
# Pattern: the test name describes the bug, not the fix
async def test_order_sync_handles_duplicate_tiktok_ids():
    """Regression: duplicate TikTok order IDs caused IntegrityError (issue #42)."""
    # Arrange: set up the conditions that trigger the bug
    existing_order = await create_order(tiktok_id="TK-123")

    # Act: perform the action that triggers the bug
    result = await sync_orders(mock_tiktok_response_with_duplicate)

    # Assert: verify the correct behavior (not the buggy behavior)
    assert result.skipped_count == 1
    assert await count_orders() == 1
```

### Test placement guidelines

| Bug Type | Test Location | Pattern |
|----------|--------------|---------|
| API endpoint returns wrong status | `tests/api/` | `TestClient` request + assert status/body |
| Service logic incorrect | `tests/services/` | Direct function call + assert output |
| Data layer corruption | `tests/data/` | Repo operation + assert DB state |
| Race condition | `tests/integration/` | Concurrent operations + assert consistency |
| Frontend rendering | `tests/web/` or `__tests__/` | Render + user-event + assert DOM |
| iOS crash | `*Tests/` | XCTest with crash-triggering input |

Run the test — **it must fail**. If it passes, your test doesn't reproduce the bug. Refine until RED.

## Step 4: Diagnose Root Cause

With the failing test in hand, trace the code path:

1. **Read the stack trace** from the failing test
2. **Trace the data flow** — follow the input from the test through the code to where it diverges from expected behavior
3. **Identify the root cause** — not just the symptom. Ask: "Why does this happen?" until you reach the actual flaw
4. **Check for siblings** — does the same pattern exist elsewhere? Search for similar code that might have the same bug

### Common root cause categories

| Category | Example | Typical Fix |
|----------|---------|-------------|
| Missing guard | No null check on optional field | Add validation before use |
| Wrong assumption | Assumed list always has items | Handle empty case |
| State mutation | Shared mutable object across requests | Copy or isolate state |
| Race condition | Concurrent writes without locking | Add transaction or lock |
| Type mismatch | String where int expected | Fix type coercion or add validation |
| Off-by-one | Wrong boundary in pagination | Fix comparison operator |
| Stale cache | Cached value not invalidated on write | Add cache invalidation |

## Step 5: Fix Minimally (GREEN)

Apply the **smallest change** that makes the failing test pass without breaking existing tests.

Rules:

- **Fix the bug, nothing else.** No refactoring, no "while I'm here" improvements, no feature additions.
- **One logical change.** If the fix touches multiple files, each change should be directly required by the fix.
- **Run the full test suite** — the new test passes AND all existing tests still pass.
- **If existing tests break**, your fix has unintended side effects. Investigate before proceeding.

### Fix verification checklist

- [ ] New regression test passes (was RED, now GREEN)
- [ ] All pre-existing tests still pass
- [ ] Fix addresses root cause, not just symptom
- [ ] No unrelated changes included

## Step 6: Refactor (Only When Green)

After the fix is verified, consider minimal cleanup only if directly related:

- Extract a shared validation function if the same guard is needed elsewhere
- Add type annotations that would have caught the bug at compile time
- Improve error messages that made diagnosis harder

Do NOT refactor unrelated code. Open a separate issue if you spot something worth improving.

## Step 7: Self-Review

Run through `review` checks scoped to the fix:

- [ ] **Reliability** — does the fix handle all variants of the triggering condition?
- [ ] **Security** — if the bug was exploitable, is the fix complete?
- [ ] **Observability** — did you add logging/metrics that would catch this class of bug earlier?
- [ ] **Siblings** — did you check for the same pattern elsewhere and fix or file issues?

## Step 8: Open the PR

Follow `ship` conventions:

- Branch: `fix/TICKET-description` (e.g., `fix/issue-42-duplicate-order-sync`)
- Commit messages: `fix(scope): description` for the fix, `test(scope): description` for the regression test
- PR body must include:
  - **Root cause** — what was wrong and why
  - **Fix** — what you changed
  - **Regression test** — link to the test that prevents recurrence
  - **Sibling check** — whether the same pattern exists elsewhere

### PR body template

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
```

## Decision: When NOT to Use This Skill

| Situation | Use Instead |
|-----------|-------------|
| Building a new feature | `workflow/build-feature` |
| Performance degradation (no functional bug) | `review` + profiling |
| Flaky test (not a production bug) | `tdd` to stabilize the test |
| Security vulnerability (needs immediate action) | Hotfix process in `ship` (SEV1) |
| Bug requires architectural change to fix properly | `discover` first to design the fix |

## Integration with Other Skills

| Skill | Relationship |
|-------|-------------|
| `tdd` | Governs the RED → GREEN → REFACTOR cycle; `fix-bug` applies it specifically to bug reproduction |
| `focus` | Loads context scoped to the affected module and its dependencies |
| `review` | Self-review gate before PR; checks fix completeness and sibling coverage |
| `ship` | Determines severity-based response time; takes over after PR approval |
| `build-ai` | Defers to `build-ai` for AI-specific bugs (prompt regression, model quality degradation) |
| `to-issues` | Files sibling issues when the same bug pattern is found elsewhere |
