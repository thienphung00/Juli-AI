---
name: ship
description: >-
  Covers CI/CD, git workflow, infrastructure, deployment, incident response, and
  rollback — prepares, validates, and plans without directly deploying. Use when
  preparing deployment artifacts, validating release readiness, generating rollout
  plans, configuring CI pipelines, or handling incidents.
---

# Launchpad

Review Agent skill for ship-readiness. Runs only after `validate` passes and a
validation artifact exists. Never ship before validation.

## Validation artifact gate (required)

Before merge or release preparation:

1. Confirm `agent-runtime/artifacts/validation/validation-issue-<n>.json` exists on the branch.
2. Assert `status == "PASS"` and `readyForMerge == true`.
3. If `readyForShip` is present, it must also be `true` (mirrors `readyForMerge`).
4. On failure, return to `validate` or `guardrails` — do not proceed.

```bash
python -c "
import json, sys
v = json.load(open('agent-runtime/artifacts/validation/validation-issue-<n>.json'))
sys.exit(0 if v.get('status')=='PASS' and v.get('readyForMerge') else 1)
"
```

Schema: [`agent-runtime/docs/schemas/validation-artifact.schema.json`](../../../agent-runtime/docs/schemas/validation-artifact.schema.json)

Everything related to shipping safely. This skill prepares deployment artifacts, validates readiness, and generates rollout plans. It NEVER directly deploys.

## Workflow

```
Code Ready → Pre-Merge Validation → Merge → Staging Deploy → Canary → Production → Monitor
```

## Pre-Merge Gate

Before any PR merges:

### Sync-before-merge (parallel / long-lived PRs)

**Required** when any other PR may have merged since this branch was cut or last rebased (always assume yes during parallel runs):

1. `git fetch origin main`
2. Rebase onto `origin/main` (or merge `origin/main` if rebase is unsuitable)
3. Resolve conflicts on the branch — do not merge a stale tip into `main`
4. Push (`--force-with-lease` after rebase)
5. Wait for CI green on the **updated** tip, then merge

Sync-at-PR-open is not enough: `main` moves when sibling PRs land. This gate is owned by Review Agent `ship` (ops lock holder executes). See [`.cursor/rules/issue-workflow.mdc`](../../../.cursor/rules/issue-workflow.mdc).

### Automated Checks (CI)

```yaml
pr-checks:
  - lint (ruff, eslint)
  - type-check (mypy, tsc)
  - unit-tests
  - integration-tests
  - ai-evals (if AI code changed)
  - security-scan (bandit, npm audit)
  - dependency-check (license, vulnerabilities)
  - migration-validation (if schema changed)
```

### Manual Checks

- [ ] PR < 400 lines (split if larger)
- [ ] Architecture decision documented (if applicable)
- [ ] API contract changes backward-compatible (or versioned)
- [ ] Feature flag wraps new behavior

## Git Workflow

### Branch Strategy

```
main (production)
  └── staging (pre-production validation)
       └── feature/TICKET-description (development)
```

### Commit Convention

```
type(scope): description

feat(inventory): add demand forecasting endpoint
fix(connector): handle TikTok rate limit gracefully
refactor(ai): extract prompt registry from handlers
docs(api): update forecasting endpoint contract
test(forecast): add golden dataset for MAPE validation
chore(deps): upgrade litellm to 1.40.0
```

### PR Template

```markdown
## What
[One sentence describing the change]

## Why
[Business context or technical motivation]

## How
[Brief implementation approach]

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing done (describe)

## Rollback
[How to revert if something goes wrong]

## Checklist
- [ ] review passed (include ai-integration checklist if AI code)
- [ ] No secrets committed
- [ ] Migrations are reversible
```

## Deployment

### Staging Validation

Before promoting to production:

1. Deploy to staging environment
2. Run smoke tests against staging
3. Verify monitoring dashboards (no error spikes)
4. Test critical user flows end-to-end
5. Validate AI quality metrics against baseline

### Production Rollout

```
Deploy to 1 instance (canary)
  → Monitor 15 minutes
  → Check error rates, latency, AI quality
  → If healthy: roll to remaining instances
  → If degraded: immediate rollback
```

### Rollback Plan

Every deployment MUST have a documented rollback:

```markdown
## Rollback: [Feature Name]

### Trigger Conditions
- Error rate > 5% (baseline: 0.5%)
- p95 latency > 2s (baseline: 500ms)
- AI quality MAPE > 25% (baseline: 18%)

### Steps
1. Revert deployment: `railway rollback` / redeploy previous image
2. If DB migration: run down migration `alembic downgrade -1`
3. If feature flag: disable flag immediately
4. Notify: post in #incidents channel

### Verification
- Error rate returns to baseline within 5 minutes
- No data corruption (run integrity check)
```

## Incident Response

### Severity Levels

| Level | Definition | Response Time | Example |
|-------|-----------|---------------|---------|
| SEV1 | System down, data loss risk | Immediate | Database corruption, full outage |
| SEV2 | Major feature broken | < 30 min | Order sync failing, AI completely down |
| SEV3 | Minor feature degraded | < 2 hours | Slow reports, intermittent cache miss |
| SEV4 | Cosmetic / low impact | Next business day | UI glitch, non-critical log noise |

### Incident Workflow

```
Detect (Sentry/Grafana alert)
  → Acknowledge (within response time)
  → Diagnose (check logs, traces, metrics)
  → Mitigate (rollback, feature flag, hotfix)
  → Communicate (status update to stakeholders)
  → Resolve (permanent fix)
  → Postmortem (within 48 hours for SEV1/2)
```

### Postmortem Template

```markdown
# Incident: [Title]

**Severity**: SEV[N]
**Duration**: [start] → [end] ([total])
**Impact**: [what users experienced]

## Timeline
- HH:MM — [event]

## Root Cause
[Technical explanation]

## Resolution
[What fixed it]

## Action Items
- [ ] [Preventive measure] — Owner — Due date
```

## Infrastructure

### Current (single VPS — see ADR-020, `docs/runbooks/app-review-runbook.md`)

- Single review VPS, `juli-api` (FastAPI/uvicorn) + `juli-web` (Next.js) as `systemd` units
- Nginx terminates TLS and reverse-proxies both
- Supabase-managed Postgres (session pooler) — not self-hosted
- Secrets fetched from AWS Secrets Manager at deploy/restart time (`fetch-secrets.sh`)
- Auto-deploy from `main` via SSH (`release.yml` → `infra/scripts/deploy-release.sh`);
  manual rollback via `rollback.yml`
- No Docker/containers, no Railway/Vercel, no staging environment yet (future TODO)

### Scale (future — not built, no infra provisioned)

- Second environment (staging) ahead of a real second VPS or managed platform
- Multiple FastAPI workers / load balancing once traffic is more than review-only
- Dedicated Postgres if Supabase free/session-pooler limits are hit
- Heavier observability (beyond `journalctl` + the 15-min uptime check) if this
  stack ever takes production traffic

### Environment Management

| Environment | Purpose | Deploy Trigger |
|-------------|---------|---------------|
| Development | Local + feature branches | Manual |
| Staging | Pre-production validation | Merge to `staging` |
| Production | Live users | Merge to `main` (after staging OK) |

## Integration with Other Skills

| Skill | Relationship |
|-------|-------------|
| `validate` | **Requires** `agent-runtime/artifacts/validation/validation-issue-<n>.json` with `readyForMerge: true` |
| `review` | Pre-merge checklist follows review; ship gates on validation artifact, not review prose |
| `focus` | Meta Agent runs harness optimization after validation; ship does not consume optimization artifacts |

## Additional Resources

- For CI configuration examples, see [ci-examples.md](ci-examples.md)
