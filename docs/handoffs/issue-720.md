# Handoff: #720 — Deploy Celery worker/beat on VPS

**Date:** 2026-08-04
**Found while:** validating #689/#633 (gold-envelope cutover) — not part of the DUX or CDP epics.

## Problem

`infra/systemd/` has exactly 5 units (`juli-api`, `juli-web`, `juli-secrets-refresh`
+timer, `juli-restore-drill` +timer). There is no Celery worker or beat unit
anywhere in this repo's infra, and `juli-api.service`'s header says explicitly:
*"App Review envelope: single web process only. Deferred background services
are out of scope for review."* `docs/runbooks/app-review-runbook.md`'s
documented install steps (Step 4) confirm the same — this is the full
documented production topology, not a review-only carve-out.

Confirmed live on the VPS: `ps aux | grep -i celery` and
`systemctl list-units --type=service --all | grep -i celery` both return
nothing. `mock_analytics_hourly_reconcile`
(`backend/src/juli_backend/workers/tasks/mock_analytics_reconcile.py`) is a
real `@celery_app.task`, and the Track A CDP chain assumes an async
worker/dispatch layer that has never run in production.

## Scope of this issue

Docs + config only, no application code changes:

1. `infra/systemd/juli-celery-worker.service` — follow `juli-api.service`'s
   exact pattern: `ExecStartPre=fetch-secrets.sh`,
   `EnvironmentFile=/etc/juli/api.env`, `WorkingDirectory=/root/releases/current`,
   `Restart=on-failure`. Command: `celery -A juli_backend.workers.celery_app worker`.
2. `infra/systemd/juli-celery-beat.service` — same pattern. Command:
   `celery -A juli_backend.workers.celery_app beat`. The schedule itself is
   already defined in code (`celery_app.py`'s `beat_schedule` — hourly mock
   analytics reconcile, per-minute CDP batch reconcile gated off by a flag) —
   do not invent a different schedule in the unit file.
3. **Redis is also not provisioned** — `infra/scripts/env/api.env.example`
   already documents `REDIS_URL`/`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`
   (commented out, per ADR-041 co-located loopback Redis) but the runbook's
   "Provision a new production VPS" step never installs `redis-server`, and
   the comment there literally says *"App Review skips Redis/workers/cron —
   leave REDIS_URL / CELERY_* unset."* Update the runbook's package list to
   include `redis-server`, and update the env example's guidance from "leave
   unset" to actionable uncomment instructions, now that the workers are
   being introduced.
4. Update `docs/runbooks/app-review-runbook.md`: add `redis-server` to the
   Step 1 package list; add both new units to the Step 4 install list, the
   "Config files in this directory" table, and the "Log commands" reference
   section; update the Redis/Celery env-var comment block in
   `infra/scripts/env/api.env.example`.

## Checked: does this conflict with the Phase 2.5 "App Review" scope guard?

`tests/unit/test_phase_2_5_deploy_config.py::test_deploy_config_excludes_out_of_scope_services`
forbids `redis`/`celery`/`worker service`/`cron`/`webhook` tokens — but only in
4 specific existing files (`juli-api.service`, `juli-web.service`, the two
nginx configs). It does not scan `infra/systemd/` as a directory, so adding
**separate, new** unit files does not trip it, and this issue does not modify
any of those 4 files. Judged this to be a stale Phase 2.5 bootstrap-era
constraint, not a live compliance boundary: ADR-041 already planned VPS Redis
+ Celery, `infra/scripts/env/api.env.example` already documents the env vars
as "leave unset **unless** a required startup path forces them" (anticipating
exactly this activation), and the entire merged CDP epic (#598/#601/#602/#630/
#631/#633) ships `@celery_app.task` code that is dead without a worker. Do not
edit that test's forbidden-token list — it remains correct for the 4 files it
checks.

## Explicitly out of scope for this issue

- Actually enabling/starting the units on the VPS (SSH-only, human follow-up).
- Seeding reference-shop data or re-running the #633/#689 post-cutover
  loopback probe — that happens after a human deploys these units.
- Any application/business logic change.

## References

- [#720](https://github.com/thienphung00/Juli-AI/issues/720)
- [#689](https://github.com/thienphung00/Juli-AI/pull/689) / [#633](https://github.com/thienphung00/Juli-AI/issues/633) — where the gap was found
- [ADR-020](../adr/020-vps-ssh-continuous-delivery-and-secrets-manager.md) — VPS deploy model
- `infra/systemd/juli-api.service` — the canonical unit pattern to follow
