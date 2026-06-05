---
name: ship
description: >-
  Covers CI/CD, git workflow, infrastructure, deployment, incident response, and
  rollback — prepares, validates, and plans without directly deploying. Use when
  preparing deployment artifacts, validating release readiness, generating rollout
  plans, configuring CI pipelines, or handling incidents.
---

# Launchpad

Everything related to shipping safely. This skill prepares deployment artifacts, validates readiness, and generates rollout plans. It NEVER directly deploys.

## Workflow

```
Code Ready → Pre-Merge Validation → Merge → Staging Deploy → Canary → Production → Monitor
```

## Pre-Merge Gate

Before any PR merges:

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

### MVP (Railway)

- Single instance per service
- Managed PostgreSQL
- Redis add-on
- Auto-deploy from `main` branch

### Scale (Hetzner VPS)

- Nginx load balancer
- Multiple FastAPI workers
- Dedicated PostgreSQL server
- Redis cluster
- Cloudflare CDN + DDoS protection

### Environment Management

| Environment | Purpose | Deploy Trigger |
|-------------|---------|---------------|
| Development | Local + feature branches | Manual |
| Staging | Pre-production validation | Merge to `staging` |
| Production | Live users | Merge to `main` (after staging OK) |

## Integration with Other Skills

| Skill | Relationship |
|-------|-------------|
| `discover` | `EXECUTION.md`, `system-design.md`, and ADRs inform deployment topology and rollback plans |
| `review` | Pre-merge checklist is the gate before ship takes over |
| `focus` | Focus loads ship when deployment/CI work is detected |

## Additional Resources

- For CI configuration examples, see [ci-examples.md](ci-examples.md)
