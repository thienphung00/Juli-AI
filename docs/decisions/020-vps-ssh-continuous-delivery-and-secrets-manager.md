# ADR 020: VPS/SSH continuous delivery + AWS Secrets Manager for runtime secrets

**Status:** Accepted  
**Date:** 2026-07-09  
**Supersedes:** the "Deployment — Railway for MVP" line in
[ADR-012](012-architecture-reconciliation-mvp-vs-target.md) (all other ADR-012 decisions —
Postgres, Haiku, real-time scope, tenant isolation — are unaffected and remain in force).  
**Related:** [ADR-003](003-ai-native-cicd-policy.md) (CI/CD enforcement layer),
[ADR-017](017-product-monorepo-deployment-architecture.md) (monorepo/deploy config split),
[`docs/phases/phase-2.5-deployment.md`](../phases/phase-2.5-deployment.md)

## Context

ADR-012 named Railway as the Phase 2 MVP deploy target. That never actually happened:
`.github/workflows/release.yml` has shipped as an `echo "Configure RAILWAY_TOKEN..."` stub
since it was written, and the real, live deployment — built out in Phase 2.5-d/2.5-review
(#253, #256–#261) — is a single VPS running `juli-api` (FastAPI/uvicorn) and `juli-web`
(Next.js) as `systemd` units behind Nginx, documented in
[`infra/deploy/app-review-runbook.md`](../../infra/deploy/app-review-runbook.md). That VPS
currently serves TikTok App Review traffic only (no production users).

`pr.yml` already gates merges (lint, type-check, tests, migration reversibility, frontend
checks). Nothing after "safe to merge" existed: no automated deploy, no rollback, no minimal
uptime monitoring, and secrets reached the VPS as a hand-edited `.env` file with no
inventory, no rotation path, and no access control beyond "whoever can SSH in."

## Decision

**Deployment target stays the existing VPS — no new compute infra.** No Docker, no
containers, no ECS/ECR/Kubernetes/EC2, no Railway, no Vercel. `release.yml` deploys over
SSH (`appleboy/ssh-action`) on every merge to `main`, running
[`infra/scripts/deploy-release.sh`](../../infra/scripts/deploy-release.sh) on the VPS.

- **Release model:** git worktrees, not overwrite-in-place. The canonical checkout
  (`~/Juli-AI-v2`) is the source of truth for `git worktree add`; each deploy creates
  `~/releases/<short-sha>/` with its own `.venv` / `apps/dashboard/node_modules`, then atomically flips
  the `~/releases/current` symlink once the new build passes a health check. Both systemd
  units run from `~/releases/current`. Keeps the last 3 releases for rollback.
- **Rollback:** manual, `workflow_dispatch`-triggered
  ([`rollback.yml`](../../.github/workflows/rollback.yml) →
  [`rollback-release.sh`](../../infra/scripts/rollback-release.sh)) — re-point the symlink to
  a previous release and restart. No blue/green, no automatic rollback-on-failure.
- **Secrets move to AWS Secrets Manager** — the one AWS *service* adopted here, for secret
  storage only; this is not a move of compute to AWS. Two secrets grouped by app
  (`juli/api/production`, `juli/web/production`), each a JSON blob of that app's env vars.
  A dedicated IAM user (`juli-vps-secrets-reader`) scoped to
  `secretsmanager:GetSecretValue` on exactly those two ARNs — no broader access, no instance
  role (the VPS isn't EC2). Static credentials live only in
  `/etc/juli/aws-credentials` on the VPS (root-owned, `chmod 600`) — never in git, never in
  GitHub Actions secrets.
- **Fetch mechanism:** [`fetch-secrets.sh`](../../infra/scripts/fetch-secrets.sh) writes
  `/etc/juli/juli-{api,web}.env`, wired as `ExecStartPre=` on both systemd units *and* called
  at the start of every deploy. Chosen over deploy-time-only fetch so a bare
  `systemctl restart` (crash, reboot) also picks up the latest secret value; the accepted
  tradeoff is an AWS dependency on every restart.
- **CI-side credentials stay minimal:** GitHub Actions only holds an SSH deploy key
  (`VPS_SSH_HOST`/`VPS_SSH_USER`/`VPS_SSH_KEY`) plus a Slack webhook for uptime alerts. No
  AWS credentials in CI — the fetch happens VPS-side.
- **Monitoring stays minimal:** a 15-minute scheduled workflow
  ([`uptime.yml`](../../.github/workflows/uptime.yml)) hits the two public health endpoints
  and posts to Slack only on failure. `journalctl -u juli-api` / `-u juli-web` remains
  sufficient for logs — no Datadog/New Relic/ELK.
- **CI hardening (`pr.yml`):** `bandit -r backend/ -ll` (medium+ severity) and
  `gitleaks/gitleaks-action` (PR-diff secret scan) as new required jobs; `pytest --cov=backend
  --cov-fail-under=80` (5 points below the measured 85% baseline at the time of this ADR, not
  an arbitrary 80%); `npm run build` added to the frontend job with the same
  `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_UI_ONLY` build-time env used in the real App Review
  deploy. `.github/dependabot.yml` covers `pip` (root `requirements.txt`), `npm` (`apps/dashboard/`),
  and `github-actions` version updates.
- **No staging environment.** One VPS, review traffic only — a second environment is an
  explicit future TODO, not built here.

## Rationale

| Factor | Why this approach |
|--------|-------------------|
| Match reality, not the stale plan | Railway was never wired up; the VPS is what's actually live and reviewer-facing |
| No new infra class | Git worktrees + symlink give release-dir rollback without Docker/containers, which the prompt explicitly ruled out |
| Least-privilege secrets | A scoped IAM user + two grouped secrets is simpler to audit than per-key secrets or broad `SecretsManagerFullAccess` |
| Minimal monitoring first | A review-only box doesn't justify a full observability stack; a 15-min health poll + Slack is proportionate |
| Coverage gate as regression guard, not aspiration | Floor is measured-then-set (85% baseline → 80% floor), so it can't immediately break the pipeline |

## Consequences

- **Positive:** merges to `main` now deploy automatically with a real health-check gate and a
  one-click rollback path; secrets have an inventory, least-privilege access, and a rotation
  flow for the first time.
- **Positive:** `pr.yml` catches medium+ severity security findings and leaked secrets before
  merge, not after.
- **Negative:** `ExecStartPre` secret fetch means a bare `systemctl restart` now depends on
  AWS Secrets Manager being reachable — an AWS outage could block a restart until the
  fetch script's failure mode is exercised in practice. Revisit if this causes a real incident.
- **Negative:** release worktrees each carry their own `.venv` / `node_modules` — more disk
  usage on the VPS than overwrite-in-place (bounded by `KEEP_RELEASES=3`).
- **Deferred, not built:** a separate staging environment/VPS; heavier observability
  (Datadog/New Relic/ELK); automated rollback-on-failure; blue/green deploys.
- ADR-012's Railway line is superseded; its Postgres/Haiku/real-time/tenant-isolation
  decisions are unaffected.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Actually wire up Railway (per ADR-012) | Would require standing up new infra for a stack that already works on the VPS; contradicts the explicit "no new infra" constraint for this pass |
| Docker/containers on the VPS | Explicitly out of scope; VPS has no container runtime today and introducing one is a bigger change than the CD problem requires |
| EC2 instance role for AWS auth | The VPS is not EC2 — would require migrating compute to AWS, which is out of scope; a scoped IAM user's static credentials on the VPS is the documented pattern for non-EC2 hosts |
| One secret per env var | More IAM ARNs to scope and more API calls per fetch; a JSON blob per app is simpler to audit and rotate |
| Deploy-time-only secret fetch | Simpler, but a rotated secret would silently stay stale until the next deploy; `ExecStartPre` was chosen so a plain restart also refreshes it |

## References

- [`infra/deploy/app-review-runbook.md`](../../infra/deploy/app-review-runbook.md) — full
  topology, secrets inventory, IAM policy, rotation flow, rollback, and log commands
- [`infra/scripts/deploy-release.sh`](../../infra/scripts/deploy-release.sh),
  [`rollback-release.sh`](../../infra/scripts/rollback-release.sh),
  [`fetch-secrets.sh`](../../infra/scripts/fetch-secrets.sh)
- [`infra/scripts/aws/iam-policy-secrets-reader.json`](../../infra/scripts/aws/iam-policy-secrets-reader.json)
- `.github/workflows/release.yml`, `rollback.yml`, `uptime.yml`, `pr.yml`
