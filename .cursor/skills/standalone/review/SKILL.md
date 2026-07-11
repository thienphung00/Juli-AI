---
name: review
description: >-
  Validates code quality across reliability, maintainability, security, observability,
  and performance — acts as reviewer, checklist provider, and patch suggester without
  generating features. Use when validating implementation, reviewing code, checking
  for missing error handling, or enforcing engineering best practices on existing or
  proposed code.
---

# Guardrails

Review Agent skill: validates code quality after Executor implementation. Owns the
`review` step in `review → validate → ship-ready`. Does not substitute for Validate.

Emits `agent-runtime/artifacts/reviews/review-issue-<n>.json` (ADR-003 CI gate + Meta fields per
[`agent-runtime/docs/agent-runtime-artifacts.md`](../../../agent-runtime/docs/agent-runtime-artifacts.md)).

## Workflow prompt cache (required)

Before review checks, load and inject per [`prompt-caching`](../prompt-caching/SKILL.md) (Review row).
After review, update **child** cache only (`workflowPhase: validate`).

A validator, reviewer, checklist provider, and patch suggester.

## Artifact emission (required)

After review completes, write or update the review artifact before handing off to
`validate`. The JSON file is the system of record — not chat output.

| Field group | Purpose |
|-------------|---------|
| ADR-003 CI | `status`, `criticalFindings`, `modulesTouched`, `testCoverage.acceptance` — consumed by `pr.yml` |
| Meta optimization | `reviewFailures`, `findings`, `securityFindings`, `architectureFindings`, `maintainabilityFindings`, `reviewDurationMs` |

### Workflow

1. Read `agent-runtime/artifacts/implementations/implementation-issue-<n>.json` when present (Executor handoff).
2. Run review checks (below) and populate `criticalFindings`.
3. Map acceptance criteria to tests in `testCoverage.acceptance.mappings`.
4. Set `status`: `FAIL` if any `criticalFindings[*].severity == "CRITICAL"` or
   `actionRequired: true`; `PASS_WITH_WARNINGS` if WARNING findings only; else `PASS`.
   **Do not** use legacy top-level `warnings[]` — all findings belong in
   `criticalFindings` with the correct `severity`.
5. Write artifact:

```bash
python agent-runtime/agent-runtime/scripts/ci/generate_review_artifact.py --issue <n> --input-json /tmp/review-fields.json
```

Merge handoff fields via `--input-json`. Existing artifact content on disk is
preserved unless you pass `--fresh` (starts from template + input only).
The generator deep-merges, normalizes findings, aligns `status`, and adds Meta fields.

### Status semantics

| `status` | When | Merge |
|----------|------|-------|
| `FAIL` | Any CRITICAL finding, mandatory fail trigger, or merge-blocking issue | Blocked |
| `PASS_WITH_WARNINGS` | WARNING findings only | Blocked until signoff + per-finding ack |
| `PASS` | No blocking findings | Allowed when validation passes |

`reviewFailures` counts findings with `severity == "CRITICAL"` or `actionRequired: true`.

### Gating WARNING findings (`PASS_WITH_WARNINGS`)

Each WARNING in `criticalFindings` must include:

```json
{
  "severity": "WARNING",
  "description": "N+1 query",
  "acceptanceByReviewer": true,
  "ownerAck": true,
  "fixedInCommit": "abc123"
}
```

Use `shipAsIsReason` instead of `fixedInCommit` when shipping as-is.

When `status` is `PASS_WITH_WARNINGS`, also set:

```json
"reviewerSignoff": {
  "statement": "I reviewed and accepted these risks",
  "timestamp": "2026-06-23T12:00:00Z",
  "acceptedRisks": true
},
"ownerSignoff": {
  "statement": "I acknowledge and will fix",
  "timestamp": "2026-06-23T12:05:00Z",
  "acknowledged": true
}
```

### ML modules (`src/modules/ml/*`)

When ML modules are touched, document gates:

```json
"mlGates": {
  "coldStartThresholdDocumented": true,
  "promotionGateDocumented": true,
  "notes": "Sparse-history hold threshold; promotion via evaluate_promotion_status",
  "thresholds": {
    "SPARSE_HISTORY_MIN_IMPRESSIONS": 50,
    "AD_PERFORMANCE_MAX_ROAS_MAPE": 50.0
  }
}
```

Missing ML gates is a mandatory `FAIL` trigger. CI also scans `thresholds.py` in
source for required constants (see `agent-runtime/scripts/ci/ml_thresholds.py`).

### Hotfix override (`overriddenMerge`)

For P0 incidents only — never for CRITICAL security or data exposure:

```json
"overriddenMerge": {
  "timestamp": "2026-06-24T08:15:00Z",
  "overriddenBy": "thien@juli.ai",
  "reason": "Production incident hotfix; P0 impact outweighs ML gate validation",
  "incidentLink": "INC-789"
}
```

Keep `status: "FAIL"`; validation passes when override clears overridable gates.

### Post-deploy feedback (`productionOutcome`)

After ship, link incidents to accepted findings (use `criticalFindings[].id`):

```json
"productionOutcome": {
  "incidents": [{
    "incidentId": "INC-456",
    "linkedFinding": "find-140-threshold",
    "shipAsIsReason": "acceptable at current scale",
    "actualOutcome": "False positive rate spiked; was NOT acceptable",
    "timestamp": "2026-07-15T09:00:00Z"
  }]
}
```

### Inputs

- Implementation artifact: `agent-runtime/artifacts/implementations/implementation-issue-<n>.json`
- GitHub issue acceptance criteria
- Changed files on branch

### Outputs

- `agent-runtime/artifacts/reviews/review-issue-<n>.json`
- Human-readable findings (markdown below) for the handoff template

Schema: [`agent-runtime/docs/schemas/review-artifact.schema.json`](../../../agent-runtime/docs/schemas/review-artifact.schema.json)

## Role

When invoked, this skill:
1. Scans code for standards violations
2. Produces a categorized findings report (Critical / Warning / Info)
3. Suggests specific patches with before/after code
4. Provides applicable checklists for the type of work

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

### 2. Maintainability

| Check | What to Look For |
|-------|-----------------|
| Function size | Functions > 30 lines or multiple responsibilities |
| Naming | Ambiguous names, abbreviations, inconsistent conventions |
| DRY violations | Duplicated logic across handlers/modules |
| Coupling | Direct imports across service boundaries |
| Complexity | Nested conditionals > 3 levels, cyclomatic complexity > 10 |

### 3. Security

| Check | What to Look For |
|-------|-----------------|
| Input sanitization | Raw user input in queries, templates, shell commands |
| Auth/authz | Missing permission checks, overly broad tokens |
| Secrets | Hardcoded keys, tokens, passwords in source |
| OWASP Top 10 | Injection, XSS, broken auth, data exposure |
| Dependency risk | Known vulnerable packages, unpinned versions |

### 4. Observability

| Check | What to Look For |
|-------|-----------------|
| Logging | Missing logs on errors, unstructured logs, PII in logs |
| Correlation IDs | Request flows without trace/span propagation |
| Metrics | New endpoints without latency/error instrumentation |
| Alerts | Critical paths without threshold-based alerting |

### 5. Performance

| Check | What to Look For |
|-------|-----------------|
| N+1 queries | Loop-based DB calls without batching |
| Missing indexes | Queries on unindexed filter/sort columns |
| Unbounded results | Queries without LIMIT, pagination missing |
| Cache misses | Repeated expensive computations without caching |
| Memory leaks | Growing collections without cleanup, unclosed resources |

## Output Format

```markdown
## Guardrails Review

### Critical (must fix before merge)
- **[Reliability]** `service/ai_forecast.py:42` — AI model call without timeout or retry
  ```python
  # Current
  result = await litellm.completion(model="gemini-flash", messages=msgs)

  # Suggested
  result = await litellm.completion(
      model="gemini-flash",
      messages=msgs,
      timeout=30,
      num_retries=3,
  )
  ```

### Warnings (should fix)
- **[Observability]** `api/orders.py:88` — Error caught but not logged
- **[Security]** `connectors/tiktok.py:15` — API key in default parameter

### Info (consider)
- **[Performance]** `reports/daily.py:60` — Could benefit from query result caching
```

## Checklists

Use the appropriate checklist based on what's being validated:

- For pre-merge validation, see [checklists/pre-merge.md](checklists/pre-merge.md)
- For AI integration validation, see [checklists/ai-integration.md](checklists/ai-integration.md)
- For API endpoint validation, see [checklists/api-endpoint.md](checklists/api-endpoint.md)

## Anti-Patterns Reference

For common anti-patterns with fix examples, see [anti-patterns.md](anti-patterns.md).

## Integration with Cursor Rules

This skill works alongside Tier 2 workspace rules (loaded via Focus):
- `.cursor/rules/reliability.mdc` — defensive programming, error handling
- `.cursor/rules/code-quality.mdc` — DRY, modularity, readability
- `.cursor/rules/observability.mdc` — structured logging, metrics, tracing
- `.cursor/rules/git-baseline.mdc` — git, CI/CD, code reviews

The rules enforce standards passively during code generation. Guardrails actively audits and patches after the fact.

## Integration with Other Skills

| Skill | How Guardrails Interacts |
|-------|------------------------|
| Executor (domain skills) | Consumes implementation artifact; uses issue acceptance criteria and `system-design.md` as validation source |
| `validate` | Review artifact is input to Validate; review does not replace deterministic gates |
| `ship` | Pre-merge checklist gates the delivery pipeline after validation passes |
| `focus` | Focus loads review selectively based on detected code patterns; Meta consumes review artifact post-validation |
