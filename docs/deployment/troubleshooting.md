# AI-Native CI/CD: Troubleshooting

Recovery playbook for the gates defined in
[ADR-003](../adr/003-ai-native-cicd-policy.md). Cross-references
[`implementation-guide.md`](implementation-guide.md) for schemas and
[`quick-reference.md`](quick-reference.md) for the cheat sheet.

---

## PR blocked: review artifact missing

### Symptom

```
PR Validation Failed: check_review_artifact
agent-runtime/artifacts/reviews/review-issue-123.json not found
```

### Causes

1. `guardrails` skill ran but did not write the artifact (or `intent-review` artifact missing upstream).
2. Filename uses the wrong pattern (`review-123.json` instead of `review-issue-123.json`).
3. Wrong directory (root `artifacts/` instead of `agent-runtime/artifacts/reviews/`).

### Fix

```bash
python agent-runtime/agent-runtime/scripts/ci/generate_review_artifact.py --issue 123
git add agent-runtime/artifacts/reviews/review-issue-123.json
git commit -m "chore: add review artifact for issue #123"
git push
```

If context was lost, resume from the driving slice in
[`EXECUTION.md`](../../EXECUTION.md) before regenerating.

---

## Acceptance criteria not mapped to tests

### Symptom

```
check_acceptance_mapping FAIL
Total: 5  Mapped: 3  Unmapped: ["Invalid OTP shows error", "OTP expires after 5 minutes"]
```

### Fix

1. Read the acceptance criteria from the issue:
   ```bash
   gh issue view 123 --json body --jq '.body' | rg -A 30 "## Acceptance Criteria"
   ```
2. Add named tests in `tests/`:
   ```python
   def test_invalid_otp_shows_error(client):
       ...

   def test_otp_expires_after_five_minutes(client):
       ...
   ```
3. Update the review artifact's `testCoverage.acceptance.mappings[]`:
   ```json
   {
     "criterion": "Login shows error on failure",
     "test": "web/src/__tests__/test_ui_only_login.test.tsx"
   }
   ```
4. Re-run locally: `python agent-runtime/agent-runtime/scripts/ci/generate_validation_artifact.py --issue 123`.

---

## MODULE.md drift

### Symptom

```
check_module_drift FAIL
Module: src/auth
Missing in MODULE.md: validate_reset_token
Excess in MODULE.md: deprecated_login
```

### Fix

1. Read the actual exports:
   ```bash
   rg "^def |^async def |^class " src/auth/__init__.py src/auth/api.py
   ```
2. Update `src/auth/MODULE.md` "Public Interfaces" to match.
3. If a symbol is internal, prefix with `_` so the AST scan ignores it.
4. Re-run: `python agent-runtime/scripts/validate/check_module_drift.py`.

Tier 3 utility modules without `MODULE.md` are exempt — see
[`docs/architecture/map.md`](../architecture/map.md).

---

## Cyclic dependency detected

### Symptom

```
check_module_boundaries FAIL
Cycle: src/auth -> src/api -> src/data -> src/auth
```

### Fix

1. Localize the offending edge:
   ```bash
   python agent-runtime/scripts/validate/check_module_boundaries.py --verbose
   ```
2. Apply one of:
   - Move shared types to a new utility module that neither side imports.
   - Use dependency inversion (pass a callable in instead of importing the module).
   - Convert runtime import to `from __future__ import annotations` + typing-only `TYPE_CHECKING` block.
3. Confirm: `python agent-runtime/scripts/validate/check_module_boundaries.py`.

---

## Context overflow: resuming an unfinished issue

### When

The session is approaching its token limit and the issue is not finished.

### Fix

1. Update the driving slice status in [`EXECUTION.md`](../../EXECUTION.md) (keep the
   checkbox unchecked, note what remains and any blockers).
2. Commit, push, open a draft PR linked to that slice.
3. Resume in a fresh session from the same slice — `EXECUTION.md` is the
   cross-session source of truth (the `docs/handoffs/` registry was removed in the
   seller-money rescope).

> The `check_handoff.py` gate still validates the *shape* of any
> `docs/handoffs/*.md` file if one is present, but handoffs are no longer the
> required continuity mechanism.

---

## ADR required but not created

### Symptom

```
check_adr FAIL
Architectural change detected (new module: src/intelligence/forecasting)
No new file in docs/adr/ for this PR
```

### Fix

1. Find the next ADR number:
   ```bash
   ls docs/adr/ | rg "^[0-9]{3}-" | sort | tail -1
   ```
2. Create `docs/adr/NNN-slug.md` matching the existing format
   ([ADR-001](../adr/001-keep-python-fastapi.md) is the template):
   - Status / Date / Deciders
   - Context / Decision / Rationale / Consequences / References
3. Add the row to [`docs/adr/README.md`](../adr/README.md).
4. Reference the ADR from the new module's `MODULE.md` and from the review
   artifact's `recommendations[]`.

Note: filename pattern is `NNN-slug.md`, NOT `adr-NNN.md`.

---

## Tests pass locally but fail in CI

### Causes (in order of frequency)

1. Postgres or Redis services not started locally.
2. Environment variables missing in CI but set in `.env`.
3. Test ordering hidden by local cache.
4. Async test not properly awaited.

### Fix

1. Reproduce locally with the CI Postgres/Redis services:
   ```bash
   docker run -d --name pg -p 5432:5432 -e POSTGRES_DB=test_db -e POSTGRES_PASSWORD=test postgres:16
   docker run -d --name rd -p 6379:6379 redis:7
   DATABASE_URL=postgresql://postgres:test@localhost:5432/test_db \
   REDIS_URL=redis://localhost:6379 \
   pytest tests/
   ```
2. Add any missing secrets via `gh secret set ... --repo <owner/repo>`.
3. Make tests order-agnostic with proper `pytest` fixtures + transactional rollback.
4. Verify `pytest-asyncio` mode is `auto` and tests are `async def` where needed.

---

## Module boundary violation detected

### Symptom

```
check_module_boundaries FAIL
Unauthorized import: src/api/v1/orders.py imports src.data.repos.orders.OrdersRepo._private_query
```

### Fix

1. Read the importee's `MODULE.md` (e.g. `src/data/MODULE.md`) to see what is
   public.
2. Either use the public surface, or, if the symbol is legitimately needed:
   - Add it to the importee's `MODULE.md` "Public Interfaces".
   - Re-export it from the module's `__init__.py`.
3. Confirm: `python agent-runtime/scripts/validate/check_module_boundaries.py`.

---

## More than 3 modules touched (warning only)

### Symptom

```
check_module_boundaries WARN
4 modules touched: src/auth, src/api, src/data, src/services/webhook
```

### Action

This is a warning, not a failure. Two options:

1. **Split** the PR into smaller ones, one per module overlap. Update the
   handoff registry status accordingly.
2. **Justify** in the PR description (last resort, e.g. a contract change that
   touches all consumers atomically).

The hard rule lives in
[`.cursor/rules/issue-workflow.mdc`](../../.cursor/rules/issue-workflow.mdc) —
issues with overlapping `Modules` are run in `Isolate` mode, not `Parallel`.

---

## Pre-PR Quick Checklist

```bash
ruff check .
mypy src/
pytest tests/
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
(cd web && npm ci && npm run lint && npm run type-check && npm run test)
python agent-runtime/agent-runtime/scripts/ci/generate_review_artifact.py --issue <N>
python agent-runtime/agent-runtime/scripts/ci/generate_validation_artifact.py --issue <N>
git status   # confirm artifacts/ is staged
git push
```

If anything fails, the JSON artifact under `agent-runtime/artifacts/validation/` lists the
exact failing check; start your fix there.
