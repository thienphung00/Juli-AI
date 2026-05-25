---
name: review
description: >-
  Universal enforcement layer for code quality. Validates reliability, maintainability,
  security, observability, and performance standards. Acts as a reviewer, checklist
  provider, and patch suggester. Use when validating implementation, reviewing code,
  checking for missing error handling, or enforcing engineering best practices.
  This skill NEVER generates features — it only validates and patches.
disable-model-invocation: true
---

# Engineering Standards

A validator, reviewer, checklist provider, and patch suggester. This skill does NOT generate features — it enforces quality on existing or proposed code.

## Role

When invoked, this skill:
1. Scans code for standards violations
2. Produces a categorized findings report
3. Suggests specific patches
4. Provides applicable checklists

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
## Engineering Standards Review

### Critical (must fix)
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
- **[Security]** `connectors/kiotviet.py:15` — API key in default parameter

### Info (consider)
- **[Performance]** `reports/daily.py:60` — Could benefit from query result caching
```

## Checklists

Use the appropriate checklist based on what's being validated:

- For pre-merge validation, see [checklists/pre-merge.md](checklists/pre-merge.md)
- For AI integration validation, see [checklists/ai-integration.md](checklists/ai-integration.md)
- For API endpoint validation, see [checklists/api-endpoint.md](checklists/api-endpoint.md)

## Anti-Patterns Reference

For common anti-patterns with fix examples, see [anti-patterns.md](anti-patterns.md)

## Integration with Cursor Rules

This skill works alongside the workspace rules:
- `.cursor/rules/reliability.mdc` — defensive programming, error handling
- `.cursor/rules/maintainability.mdc` — DRY, modularity, readability
- `.cursor/rules/observability.mdc` — structured logging, metrics, tracing
- `.cursor/rules/dev-workflow.mdc` — git, CI/CD, code reviews

The rules enforce standards passively during generation. This skill actively audits and patches after the fact.
