# ADR 027: Database migration safety pipeline — local dev gate, DB-identity guard, restore drills

**Status:** Accepted
**Date:** 2026-07-16
**Related:** [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) (VPS/SSH CD — release model this extends), [ADR-003](003-ai-native-cicd-policy.md) (AI-native CI/CD policy)

## Context

On 2026-07-13, a local `alembic upgrade head` was run against the same pooler
`DATABASE_URL` as the production VPS (App Review Supabase project). Schema landed at
head; `tiktok_credentials` came back empty. Diagnosis confirmed Alembic migrations in
this codebase are **schema-only** — they apply DDL and never copy or back up OAuth,
commerce, or sync-cursor rows (`CONTEXT.md` § Architecture, "Schema-only migration").
Recovery was explicitly declined in favor of a forward-looking fix only.

The same day, commit `9285f8bf` shipped a response for the **production deploy path**:
[`infra/scripts/safe-alembic-upgrade.sh`](../../infra/scripts/safe-alembic-upgrade.sh)
wraps `alembic upgrade head` inside `deploy-release.sh` with a pre-migration `pg_dump`,
row-count snapshots across 7 protected tables (`users`, `shops`, `tiktok_credentials`,
`orders`, `products`, `inventory_items`, `tiktok_sync_state`), a post-migration
row-count + token-decrypt verification, and an abort-with-restore-command on
regression — all before the release cuts over, so a caught regression never reaches
live traffic. `pr.yml`'s `migration-check` job already runs an upgrade → downgrade -1
→ re-upgrade reversibility check on every PR.

That leaves three gaps, surfaced by re-grilling the original incident
([grill transcript](../../CONTEXT.md), Jul 13 session, Questions 4–8):

1. **Local dev has no gate at all.** The incident itself happened locally — the exact
   workflow that caused the data loss remains unprotected today.
2. **No DB-identity guard.** Nothing prints or confirms which Supabase project a
   `DATABASE_URL` actually resolves to before migrating — the first diagnostic
   question after the incident had to be answered manually, after the fact.
3. **Backups are unverified.** `safe-alembic-upgrade.sh` prints a `pg_restore` command
   on failure, but nothing has ever proven that command actually restores a working
   database from a real backup file.

## Decision

Extend the existing gate rather than build a parallel mechanism.

1. **Local dev gets the same backup + row-count gate as production.** A local-dev
   entry point reuses `safe_alembic_helpers.py` / `safe_alembic_compare.py` (the same
   helpers `safe-alembic-upgrade.sh` already uses) to back up to a local directory and
   check row-count invariants before every local `alembic upgrade head`. Root/
   `backend/README.md` local-setup instructions point at the wrapper instead of the
   raw Alembic command.
2. **DB-identity is always printed; locally confirmed.** Before migrating, the gate
   resolves and logs the Supabase project ref (or "local/non-Supabase host") parsed
   from the connection string. Production/CI stays **non-interactive** — a deploy must
   never hang on a TTY prompt. Local runs require an interactive "yes, this is the
   right project" confirmation before the backup/migration proceeds.
3. **No new alerting.** Deploy/migration failures continue to surface only as failed
   GitHub Actions runs. `SLACK_WEBHOOK_URL` (already used by `uptime.yml`) is
   deliberately not wired into `release.yml` in this pass.
4. **A weekly automated restore drill runs on the VPS, not in CI.** A systemd timer —
   matching the existing `juli-api` / `juli-web` unit pattern, no Docker, no new
   compute class — restores the most recent `pg_dump` backup into a scratch
   schema/database on the same Postgres instance, re-runs the row-count and
   token-decrypt checks against the restored copy, then drops the scratch schema/DB
   and logs a pass/fail line for `journalctl`. The backup file never leaves the VPS —
   no GitHub Actions job pulls or receives a dump containing OAuth tokens and
   commerce PII.

## Consequences

- **Positive:** the exact failure mode from the Jul 13 incident (local migration, no
  backup, no project confirmation) now has a gate at the point where it actually
  occurred, not only at the VPS deploy step.
- **Positive:** a corrupt or incompatible backup is caught within a week instead of
  being discovered during a real recovery, when it is too late to matter.
- **Positive:** no new infrastructure class (systemd timer mirrors existing units) and
  no new secret/credential exposure — backups stay VPS-local for both production and
  the drill.
- **Negative:** local `alembic upgrade head` becomes slower (a `pg_dump` on every
  migration) and occasionally interactive (project confirmation) — an accepted
  tradeoff given this is exactly the workflow that caused the incident.
- **Negative:** the restore drill adds disk/CPU load to the single production VPS on
  a schedule; it must run at a low-traffic time and must not race
  `BACKUP_RETENTION_DAYS` rotation deleting the backup file mid-restore.
- **Deferred, not built:** Slack alerting on migration/deploy failure; a real staging
  environment for restore drills (still explicitly out of scope per ADR-020).

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| No local dev gate; runbook/discipline only | This is exactly what failed before — a human ran a migration without checking which database they were pointed at |
| Ship the local gate as a fully separate script, duplicating row-count/backup logic | Two independent implementations of the same safety logic drift apart silently; reusing `safe_alembic_helpers.py` keeps one source of truth |
| Restore drill via GitHub Actions pulling the backup over SSH | Transfers a dump containing OAuth tokens and commerce PII off the VPS to a CI runner for a marginal visibility gain over VPS-local logs |
| Hard-fail on any `DATABASE_URL` that isn't an exact allowlisted project ref (`--env` flag) | More rigid than the actual ambiguity requires; an interactive confirmation solves the same problem without a brittle allowlist to maintain across environments |

## References

- [`infra/scripts/safe-alembic-upgrade.sh`](../../infra/scripts/safe-alembic-upgrade.sh),
  [`safe_alembic_helpers.py`](../../infra/scripts/safe_alembic_helpers.py),
  [`safe_alembic_compare.py`](../../infra/scripts/safe_alembic_compare.py) — existing
  production gate this ADR extends
- `CONTEXT.md` § Architecture — "Schema-only migration", "Migration safety gate"
- [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) — release model,
  systemd unit pattern, no-Docker/no-new-infra constraint
