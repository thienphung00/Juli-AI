---
name: guardrails
description: >-
  Enforces reliability, security, observability, and performance checklists;
  suggests patches; maps acceptance-criteria coverage; emits the ADR-003 review
  artifact. Use after intent-review in the Review Agent phase, or when checking
  engineering Guardrails on proposed code — not for Spec intent-match or Fowler
  smell blocking judgment.
---

# Guardrails

Review Agent skill for **domain quality gates** and the ADR-003 review artifact.
Owns the `guardrails` step in:

`intent-review` → `guardrails` → `validate` → ship-ready

| Owns | Does NOT do |
|------|-------------|
| Reliability / security / observability / performance checklists | Re-run smell-baseline |
| Patch suggestions (before/after) | Re-audit naming/DRY/structure already judged by intent-review |
| ADR-003 `review-issue-<n>.json` | Re-judge Spec **intent-match** (`spec_fidelity` is given) |
| AC **coverage** gaps (requirement-to-test) when `spec_fidelity == pass` | Treat coverage gap as Spec fidelity failure |

Boundaries: [`../intent-review/BOUNDARY.md`](../intent-review/BOUNDARY.md).

Does **not** generate features. Does **not** substitute for Validate.

## Intent-review handoff (required)

Before any Guardrails domain check:

1. Load `agent-runtime/artifacts/intent-reviews/intent-review-issue-<n>.json`.
   If missing in a full Review Agent run → **FAIL** (do not invent Spec judgment).
2. Read `spec_fidelity` **as given** — never re-check intent-to-code fidelity.
3. If `spec_fidelity == "fail"`:
   - Add a CRITICAL finding citing intent-review (type `other` / description notes Spec fidelity fail).
   - **Skip** AC coverage-gap analysis this run (fix intent first).
   - Still fold blocking `smells` / `convention_notes` into `criticalFindings`.
4. If `spec_fidelity == "pass"`:
   - Run AC **coverage** only: each acceptance criterion needs corresponding test/behavior.
   - Coverage gap ≠ Spec fidelity fail — keep them distinct in findings.
5. Import blocking smells/convention notes into `criticalFindings`; do **not** re-scan
   for Mysterious Name / Duplicated Code / Feature Envy / etc. from scratch.

## Artifact emission (required)

After Guardrails checks, write or update the review artifact before `validate`.
The JSON file is the system of record — not chat output.

| Field group | Purpose |
|-------------|---------|
| ADR-003 CI | `status`, `criticalFindings`, `modulesTouched`, `testCoverage.acceptance` — consumed by `pr.yml` |
| Meta optimization | `reviewFailures`, `findings`, `securityFindings`, `architectureFindings`, `maintainabilityFindings`, `reviewDurationMs` |

### Workflow

1. Read intent-review artifact (required) and implementation artifact when present.
2. Apply handoff rules above.
3. Run Guardrails domains (below) — **not** Maintainability/smell re-audit.
4. When `spec_fidelity == pass`, map ACs → tests in `testCoverage.acceptance.mappings`;
   flag **coverage gaps** only.
5. Set `status`: `FAIL` if any CRITICAL / `actionRequired`; `PASS_WITH_WARNINGS` if
   WARNING only; else `PASS`. No legacy top-level `warnings[]`.
6. Write artifact:

```bash
python agent-runtime/scripts/ci/generate_review_artifact.py --issue <n> --input-json /tmp/review-fields.json
```

Set `reviewedBy` to `guardrails skill`.

### Status semantics

| `status` | When | Merge |
|----------|------|-------|
| `FAIL` | Any CRITICAL finding, Spec fidelity fail from intent-review, mandatory fail trigger | Blocked |
| `PASS_WITH_WARNINGS` | WARNING findings only | Blocked until signoff + per-finding ack |
| `PASS` | No blocking findings | Allowed when validation passes |

### Gating WARNING findings (`PASS_WITH_WARNINGS`)

Each WARNING in `criticalFindings` must include `acceptanceByReviewer`, `ownerAck`,
and `fixedInCommit` or `shipAsIsReason`, plus `reviewerSignoff` / `ownerSignoff`
objects when status is `PASS_WITH_WARNINGS` (same shape as before).

### ML modules / hotfix override / productionOutcome

Unchanged — see prior Guardrails fields: `mlGates`, `overriddenMerge`, `productionOutcome`.

### Inputs

- **Required:** `agent-runtime/artifacts/intent-reviews/intent-review-issue-<n>.json`
- Implementation artifact when present
- GitHub issue **acceptance criteria** (for coverage mapping only when Spec pass)
- Changed files on branch

### Outputs

- `agent-runtime/artifacts/reviews/review-issue-<n>.json`
- Human-readable Guardrails findings

Schema: [`agent-runtime/docs/schemas/review-artifact.schema.json`](../../../agent-runtime/docs/schemas/review-artifact.schema.json)

## Role

1. Consume intent-review contract without re-litigating Spec or smells
2. Scan for reliability / security / observability / performance gaps
3. Categorize findings (Critical / Warning / Info) and suggest patches
4. Map AC **coverage** when Spec fidelity passed
5. Emit ADR-003 review artifact

## Validation Domains

### 1. Reliability

| Check | What to Look For |
|-------|-----------------|
| Error handling | Silent `except: pass`, missing try/catch on I/O |
| Timeouts | HTTP calls, DB queries, AI model calls without timeout |
| Retries | External calls without retry + exponential backoff |
| Fallbacks | Single point of failure without degradation path |
| Input validation | Missing type checks, boundary checks, null guards |
| Idempotency | Non-idempotent operations on retry-able paths |

### 2. Security

| Check | What to Look For |
|-------|-----------------|
| Input sanitization | Raw user input in queries, templates, shell commands |
| Auth/authz | Missing permission checks, overly broad tokens |
| Secrets | Hardcoded keys, tokens, passwords in source |
| OWASP Top 10 | Injection, XSS, broken auth, data exposure |
| Dependency risk | Known vulnerable packages, unpinned versions |

### 3. Observability

| Check | What to Look For |
|-------|-----------------|
| Logging | Missing logs on errors, unstructured logs, PII in logs |
| Correlation IDs | Request flows without trace/span propagation |
| Metrics | New endpoints without latency/error instrumentation |
| Alerts | Critical paths without threshold-based alerting |

### 4. Performance

| Check | What to Look For |
|-------|-----------------|
| N+1 queries | Loop-based DB calls without batching |
| Missing indexes | Queries on unindexed filter/sort columns |
| Unbounded results | Queries without LIMIT, pagination missing |
| Cache misses | Repeated expensive computations without caching |
| Memory leaks | Growing collections without cleanup, unclosed resources |

**Structure / naming / DRY / coupling / Fowler smells:** owned exclusively by
`intent-review`. Do not re-run those checks here. If the intent-review artifact
listed smells, promote them into `criticalFindings` — do not rediscover them.

## Output Format

```markdown
## Guardrails Review

### Intent-review contract
- spec_fidelity: pass | fail (as given)
- smells imported: N | convention_notes imported: N

### Critical (must fix before merge)
- **[Reliability]** `service/ai_forecast.py:42` — AI model call without timeout or retry
  ```python
  # Suggested patch...
  ```

### Warnings (should fix)
- **[Observability]** `api/orders.py:88` — Error caught but not logged

### AC coverage (only if spec_fidelity == pass)
- Gap: AC "…" has no corresponding test/behavior
```

## Checklists

- [checklists/pre-merge.md](checklists/pre-merge.md)
- [checklists/ai-integration.md](checklists/ai-integration.md)
- [checklists/api-endpoint.md](checklists/api-endpoint.md)

## Anti-Patterns

See [anti-patterns.md](anti-patterns.md) — prefer reliability/security/observability/performance
examples; structural anti-patterns belong to intent-review.

## Integration with Cursor Rules

- `.cursor/rules/reliability.mdc`, `security.mdc`, `observability.mdc`, `performance.mdc`
- Do **not** use `code-quality.mdc` here to re-litigate structure (intent-review)

## Integration with Other Skills

| Skill | How Guardrails interacts |
|-------|--------------------------|
| `intent-review` | Required upstream; Spec + smells consumed as given |
| Executor | Implementation artifact + ACs for coverage only |
| `validate` | Consumes review artifact; Guardrails does not run gates |
| `ship` | After validation PASS |
| `focus` | Loads on Review phase / Guardrails-relevant detections |
